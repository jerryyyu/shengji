"""Focused tests for the opt-in compact play batch transport."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace

import pytest

from shengji.luna import game
from shengji.luna.token_batch import (
    BATCH_OUTPUT_SCHEMA,
    CompactBatchTransport,
    compact_packet,
    compact_prompt,
    decode_batch,
)
from shengji.luna.transport import (
    CODE_MODE_DISABLED_DIAGNOSTIC,
    CodexTurnTransportError,
    InvocationResult,
)
from shengji.luna.turn import DecisionPacket, PhaseContext, TeamMemory


SECRET = b"luna-rpc-transport-secret-32b!!!"
COORDINATES = (("2", 0, 0), ("2", 0, 1), ("2", 1, 0), ("2", 1, 1))


def packet(index: int) -> DecisionPacket:
    coordinate = COORDINATES[index]
    session_game = game.LunaSelfPlayGame(
        game.build_root(SECRET, coordinate), coordinate=coordinate,
        seed_secret=SECRET)
    team = session_game.acting_team
    observed = session_game.session(team).observe()
    memory = TeamMemory.initial(team, game._state_digest(session_game.rnd, team))
    return DecisionPacket.from_observation(
        observed, coordinate=coordinate, mirror=0, team=team, decision_index=0,
        memory=memory, phase=PhaseContext())


def batch_trace(final: object, usage: dict[str, int] | None = None) -> bytes:
    usage = usage or {"input_tokens": 11, "cached_input_tokens": 3,
                      "cache_write_input_tokens": 0, "output_tokens": 9,
                      "reasoning_output_tokens": 4}
    rows = [
        {"type": "thread.started"},
        {"type": "item.completed", "item": {"id": "d", "type": "error",
         "message": CODE_MODE_DISABLED_DIAGNOSTIC}},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "m", "type": "agent_message",
         "text": json.dumps(final, separators=(",", ":"))}},
        {"type": "turn.completed", "usage": usage},
    ]
    return b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n"
                    for row in rows)


class Run:
    def __init__(self, *, malformed: object = None, reverse: bool = False):
        self.calls = []
        self.malformed = malformed
        self.reverse = reverse

    def __call__(self, command, prompt, workspace, timeout):
        self.calls.append((command, prompt, workspace, timeout))
        context = json.loads(prompt.decode().split("BATCH_CONTEXT_JSON\n", 1)[1])
        final = self.malformed if self.malformed is not None else {
            "decisions": [{"slot": row["slot"],
                           "candidate_index": row["slot"] % 2,
                           "confidence": "medium",
                           "planning_note": f"plan-{row['slot']}"}
                          for row in context]}
        if self.reverse and self.malformed is None:
            final["decisions"].reverse()
        raw = json.dumps(final, separators=(",", ":"))
        Path(command[command.index("--output-last-message") + 1]).write_text(raw)
        return InvocationResult(0, batch_trace(final), b"", 8)


def transport(tmp_path, runner):
    return CompactBatchTransport(
        codex_binary="/usr/bin/true", temp_root=tmp_path, run_command=runner,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"})


def test_compaction_is_lossless_and_prompt_has_stable_prefix():
    first = packet(0)
    compact = compact_packet(first, 0)
    assert compact["state"] == first.state
    assert compact["candidates"] == [list(row) for row in first.candidates]
    assert compact["team_plan"] == first.memory.strategy_note
    assert not {"coordinate", "decision_sha256", "memory", "budget"} & set(compact)
    assert compact_prompt([first]).startswith(
        "You are PT-Luna, a full-information Shengji teacher")
    assert "independent unrelated games" in compact_prompt([first])


def test_batch_schema_is_identical_for_all_sizes():
    assert BATCH_OUTPUT_SCHEMA["properties"]["decisions"]["maxItems"] == 4
    assert BATCH_OUTPUT_SCHEMA["additionalProperties"] is False
    assert BATCH_OUTPUT_SCHEMA["properties"]["decisions"]["items"][
        "additionalProperties"] is False


@pytest.mark.parametrize("mutation", [
    lambda p: replace(p, phase_planning_note="already planned"),
    lambda p: replace(p, phase=PhaseContext(2), rollouts=({"result": 1},)),
])
def test_compaction_rejects_non_phase_one_or_phase_note(mutation):
    with pytest.raises(CodexTurnTransportError):
        compact_packet(mutation(packet(0)), 0)


@pytest.mark.parametrize("bad", [
    {"decisions": []},
    {"decisions": [{"slot": 0, "candidate_index": 0,
                     "confidence": "medium", "planning_note": "x",
                     "extra": 1}]},
    {"decisions": [{"slot": True, "candidate_index": 0,
                     "confidence": "medium", "planning_note": "x"}]},
])
def test_decode_rejects_closed_shape_slot_and_count(bad):
    with pytest.raises(CodexTurnTransportError):
        decode_batch(bad, [packet(0)])


def test_transport_reorders_by_slot_and_splits_usage(tmp_path):
    runner = Run(reverse=True)
    first, second = packet(0), packet(1)
    responses = transport(tmp_path, runner).call_many([second, first])
    assert len(responses) == 2
    assert responses[0].packet_sha256 == second.sha256
    assert responses[1].packet_sha256 == first.sha256
    assert [(r.intent.candidate_index, r.intent.planning_note) for r in responses] == [(0, "plan-0"), (1, "plan-1")]
    assert sum(response.usage.input_tokens for response in responses) == 11
    assert sum(response.usage.cached_input_tokens for response in responses) == 3
    assert sum(response.usage.output_tokens for response in responses) == 9
    assert sum(response.usage.reasoning_output_tokens for response in responses) == 4
    assert runner.calls[0][2].exists() is False


def test_duplicate_coordinate_is_rejected_before_runner(tmp_path):
    runner = Run()
    first = packet(0)
    duplicate = replace(first, mirror=1)
    with pytest.raises(CodexTurnTransportError, match="coordinate"):
        transport(tmp_path, runner).call_many([first, duplicate])
    assert runner.calls == []


def test_invalid_provider_batch_keeps_engine_uninvolved_and_evidence(tmp_path):
    runner = Run(malformed={"decisions": [{"slot": 0, "candidate_index": 999,
                                             "confidence": "low",
                                             "planning_note": "bad"}]})
    active = transport(tmp_path, runner)
    with pytest.raises(CodexTurnTransportError):
        active.call_many([packet(0)])
    assert active.last_evidence is not None
    assert active.last_evidence["accepted"] is False
    assert active.last_evidence["final_base64"] is not None
    assert active.last_evidence["stdout_base64"] is not None


def _valid_decisions(packets):
    return {"decisions": [{"slot": slot, "candidate_index": 0,
                           "confidence": "low", "planning_note": "ok"}
                          for slot, _packet in enumerate(packets)]}


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[:1],
    lambda rows: rows + [{"slot": 2, "candidate_index": 0,
                          "confidence": "low", "planning_note": "extra"}],
    lambda rows: [{**rows[0], "slot": 1}, {**rows[1], "slot": 1}],
    lambda rows: [{**rows[0], "slot": 0}, {**rows[1], "slot": 2}],
    lambda rows: [{**rows[0], "candidate_index": 999}, rows[1]],
])
def test_decode_rejects_duplicate_missing_extra_wrong_slot_and_range(mutation):
    packets = [packet(0), packet(1)]
    value = _valid_decisions(packets)
    value["decisions"] = mutation(value["decisions"])
    with pytest.raises(CodexTurnTransportError):
        decode_batch(value, packets)


def test_decode_valid_first_invalid_second_refuses_whole_batch():
    packets = [packet(0), packet(1)]
    value = _valid_decisions(packets)
    value["decisions"][1]["candidate_index"] = len(packets[1].candidates)
    with pytest.raises(CodexTurnTransportError):
        decode_batch(value, packets)


def test_four_packet_batch_is_supported(tmp_path):
    responses = transport(tmp_path, Run()).call_many([packet(i) for i in range(4)])
    assert len(responses) == 4
    assert sum(response.usage.total_tokens for response in responses) == 20


def test_invalid_usage_keeps_raw_refusal_evidence(tmp_path):
    class BadUsageRun(Run):
        def __call__(self, command, prompt, workspace, timeout):
            result = super().__call__(command, prompt, workspace, timeout)
            raw = result.stdout.replace(b'"cached_input_tokens":3',
                                         b'"cached_input_tokens":999')
            return InvocationResult(result.returncode, raw, result.stderr, result.wall_ms)

    active = transport(tmp_path, BadUsageRun())
    with pytest.raises(ValueError):
        active.call_many([packet(0)])
    assert not active.last_evidence["accepted"]
    assert active.last_evidence["usage"] is None
    assert active.last_evidence["stdout_base64"]

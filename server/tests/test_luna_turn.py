"""Focused can-fail tests for the supervisor-owned Luna turn RPC."""

from __future__ import annotations

import pytest

from shengji.luna import game as selfplay
from shengji.luna.turn import (
    CONTINUATIONS, DecisionPacket, Intent, PhaseContext, PlannerResponse,
    TeamMemory, TurnDriver, TurnValidationError, Usage,
)


SECRET = b"luna-turn-rpc-secret-32-bytes!!!"
assert len(SECRET) == 32


def game():
    coordinate = ("2", 0, 0)
    return selfplay.LunaSelfPlayGame(
        selfplay.build_root(SECRET, coordinate), coordinate=coordinate,
        seed_secret=SECRET)


def usage():
    return Usage(10, 2, 12, 1)


class Fake:
    def __init__(self, *, rollouts=False, play_note="play"):
        self.rollouts = rollouts
        self.play_note = play_note
        self.calls = []
        self.concurrent = 0
        self.max_concurrent = 0

    def call(self, packet):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            self.calls.append(packet)
            if self.rollouts and packet.phase.phase <= 2:
                intent = Intent(
                    "rollout", packet.decision_sha256,
                    candidate_indices=(0,), continuations=("smart-all",),
                    planning_note=f"measure-phase-{packet.phase.phase}")
                return PlannerResponse(
                    intent, usage(), team=packet.team,
                    packet_sha256=packet.sha256,
                    memory_sha256=packet.memory.sha256,
                    provider_request_sha256=packet.sha256,
                    provider_response_sha256="f" * 64)
            intent = Intent(
                "play", packet.decision_sha256, candidate_index=0,
                confidence="low", planning_note=self.play_note)
            return PlannerResponse(
                intent, usage(), team=packet.team,
                packet_sha256=packet.sha256,
                memory_sha256=packet.memory.sha256,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="f" * 64)
        finally:
            self.concurrent -= 1


def test_four_contested_decisions_alternate_identities_and_hide_peer_memory():
    rnd = game()
    fake = Fake()
    driver = TurnDriver(rnd, fake)
    evidence = driver.run(max_decisions=4)
    assert len(evidence) == 4
    assert [row.team for row in evidence] == [0, 1, 0, 1]
    assert fake.max_concurrent == 1
    assert all("peer" not in packet.payload() for packet in fake.calls)
    assert all(packet.memory.team == packet.team for packet in fake.calls)


def test_decision_packet_refuses_memory_from_the_opposing_team():
    rnd = game()
    observation = rnd.session(rnd.acting_team).observe()
    team = rnd.acting_team
    peer_memory = TeamMemory.initial(
        1 - team, selfplay._state_digest(rnd.rnd, 1 - team))

    with pytest.raises(TurnValidationError, match=r"^memory team mismatch$"):
        DecisionPacket.from_observation(
            observation, coordinate=rnd.coordinate, mirror=rnd.mirror,
            team=team, decision_index=0, memory=peer_memory,
            phase=PhaseContext())


def test_supervisor_refuses_peer_memory_before_transport_or_engine_mutation():
    rnd = game()
    fake = Fake()
    driver = TurnDriver(rnd, fake)
    team = rnd.acting_team
    before = selfplay._state_snapshot(rnd.rnd)
    driver._memories[team] = driver._memories[1 - team]

    with pytest.raises(TurnValidationError, match=r"^memory team mismatch$"):
        driver.step()

    assert fake.calls == []
    assert selfplay._state_snapshot(rnd.rnd) == before


def test_two_rollout_phases_then_play_and_canonical_evidence():
    rnd = game()
    fake = Fake(rollouts=True)
    driver = TurnDriver(rnd, fake)
    # Keep rollout tests deterministic and cheap while exercising the real
    # LunaTeamSession validation/cache/budget path.
    rnd.evaluate = lambda team, index, continuation: {
        "candidate_index": index, "continuation": continuation,
        "rollout_points": 80, "team_signed_level_utility": 1}
    rows = driver.run(max_decisions=1)
    assert [row.phase for row in rows] == [1, 2, 3]
    assert rows[-1].after_state_sha256 != rows[-1].before_state_sha256
    assert rows[0].payload() == rows[0].payload()
    assert len(fake.calls) == 3
    assert len(fake.calls[1].rollouts) == 1
    assert len(fake.calls[2].rollouts) == 2
    assert [packet.phase_planning_note for packet in fake.calls] == [
        "", "measure-phase-1", "measure-phase-2"]


def test_latest_rollout_plan_becomes_durable_when_play_note_is_empty():
    rnd = game()
    fake = Fake(rollouts=True, play_note="")
    driver = TurnDriver(rnd, fake)
    rnd.evaluate = lambda team, index, continuation: {
        "candidate_index": index, "continuation": continuation,
        "rollout_points": 80, "team_signed_level_utility": 1}
    team = rnd.acting_team
    driver.run(max_decisions=1)
    assert driver._memories[team].strategy_note == "measure-phase-2"


def test_rollout_cannot_mutate_the_live_engine(monkeypatch):
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    original = selfplay.LunaTeamSession.rollout
    def mutate(self, request):
        result = original(self, request)
        self.game.rnd.attacker_points += 1
        return result
    monkeypatch.setattr(selfplay.LunaTeamSession, "rollout", mutate)
    with pytest.raises(TurnValidationError, match="rollout mutated"):
        TurnDriver(rnd, Fake(rollouts=True)).run(max_decisions=1)
    assert selfplay._state_snapshot(rnd.rnd) != before
    assert not rnd.trajectory._events


def test_supervisor_model_budget_is_in_every_packet_and_can_fail():
    model_budget = {
        "remaining_game_wall_ms": 10_000,
        "remaining_game_tokens": 100_000,
        "remaining_scientific_wall_ms": 20_000,
        "remaining_scientific_tokens": 200_000,
    }
    rnd = game()
    fake = Fake()
    TurnDriver(rnd, fake, budget_provider=lambda: model_budget).run(
        max_decisions=1)
    assert fake.calls[0].budget["model"] == model_budget

    bad = dict(model_budget, remaining_game_tokens=-1)
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    with pytest.raises(TurnValidationError, match="model budget"):
        TurnDriver(rnd, Fake(), budget_provider=lambda: bad).run(
            max_decisions=1)
    assert selfplay._state_snapshot(rnd.rnd) == before


def test_returned_usage_is_accepted_before_play_mutates_engine():
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    accepted = []
    def reject(value):
        accepted.append(value.total_tokens)
        raise TurnValidationError("game token cap crossed")
    with pytest.raises(TurnValidationError, match="token cap"):
        TurnDriver(rnd, Fake(), usage_acceptor=reject).run(max_decisions=1)
    assert accepted == [12]
    assert selfplay._state_snapshot(rnd.rnd) == before


def test_response_identity_is_accepted_before_play_mutates_engine():
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    accepted = []
    def reject(response):
        accepted.append(response.provider_response_sha256)
        raise TurnValidationError("scientific token ledger crossed")
    with pytest.raises(TurnValidationError, match="scientific token"):
        TurnDriver(rnd, Fake(), response_acceptor=reject).run(max_decisions=1)
    assert len(accepted) == 1 and len(accepted[0]) == 64
    assert selfplay._state_snapshot(rnd.rnd) == before


def test_dispatch_reservation_refuses_before_provider_or_engine():
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    fake = Fake()
    packets = []
    def reject(packet):
        packets.append(packet.sha256)
        raise TurnValidationError("scientific dispatch budget refused")
    with pytest.raises(TurnValidationError, match="dispatch budget"):
        TurnDriver(rnd, fake, dispatch_reserver=reject).run(max_decisions=1)
    assert len(packets) == 1 and len(packets[0]) == 64
    assert fake.calls == []
    assert selfplay._state_snapshot(rnd.rnd) == before


@pytest.mark.parametrize("bad", [True, -1, 99, 1.0])
def test_invalid_candidate_index_fails_without_engine_or_memory_mutation(bad):
    rnd = game()
    packet_sha = selfplay._state_digest(rnd.rnd, 0)
    before = selfplay._state_snapshot(rnd.rnd)

    class Bad:
        def call(self, packet):
            return PlannerResponse(Intent(
                "play", packet.decision_sha256, candidate_index=bad,
                confidence="low", planning_note="bad"), usage(),
                team=packet.team, packet_sha256=packet.sha256,
                memory_sha256=packet.memory.sha256,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="f" * 64)

    # bool/negative/float are rejected while constructing Intent; out of range
    # is rejected by the driver after the packet's exact ballot is known.
    driver = TurnDriver(rnd, Bad())
    memory = driver.memories[0]
    with pytest.raises(TurnValidationError):
        driver.run(max_decisions=1)
    assert selfplay._state_digest(rnd.rnd, 0) == packet_sha
    assert selfplay._state_snapshot(rnd.rnd) == before
    assert driver.memories[0] == memory


def test_wrong_hash_tool_event_usage_and_duplicate_batch_fail_before_mutation():
    with pytest.raises(TurnValidationError):
        Intent("rollout", "0" * 64, candidate_indices=(0, 0),
               continuations=("smart-all",), planning_note="duplicate")
    with pytest.raises(TurnValidationError):
        Intent("rollout", "0" * 64, candidate_indices=tuple(range(5)),
               continuations=tuple(CONTINUATIONS), planning_note="excess")
    with pytest.raises(TurnValidationError):
        Usage.from_mapping({"schema": "pt-luna-usage-v1", "input_tokens": -1,
                            "output_tokens": 1, "total_tokens": 0, "wall_ms": 1})
    rnd = game()
    driver = TurnDriver(rnd, Fake())
    before = selfplay._state_snapshot(rnd.rnd)

    class Wrong:
        def call(self, packet):
            return PlannerResponse(Intent(
                "play", "0" * 64, candidate_index=0, confidence="low",
                planning_note="wrong"), usage(),
                team=packet.team, packet_sha256=packet.sha256,
                memory_sha256=packet.memory.sha256,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="f" * 64)

    with pytest.raises(TurnValidationError, match="stale"):
        TurnDriver(rnd, Wrong()).run(max_decisions=1)
    assert selfplay._state_snapshot(rnd.rnd) == before


def test_team_memory_binding_and_transport_exception_fail_without_commit():
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)

    class WrongTeam:
        def call(self, packet):
            return PlannerResponse(Intent(
                "play", packet.decision_sha256, candidate_index=0,
                confidence="low", planning_note="wrong"), usage(),
                team=1 - packet.team,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="f" * 64)

    with pytest.raises(TurnValidationError, match="team"):
        TurnDriver(rnd, WrongTeam()).run(max_decisions=1)
    assert selfplay._state_snapshot(rnd.rnd) == before

    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)

    class Tools:
        def call(self, packet):
            return PlannerResponse(Intent(
                "play", packet.decision_sha256, candidate_index=0,
                confidence="low", planning_note="tools"), usage(), 1,
                team=packet.team, packet_sha256=packet.sha256,
                memory_sha256=packet.memory.sha256,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="f" * 64)

    with pytest.raises(TurnValidationError, match="tool"):
        TurnDriver(rnd, Tools()).run(max_decisions=1)
    assert selfplay._state_snapshot(rnd.rnd) == before

    class Explodes:
        def call(self, packet):
            raise RuntimeError("provider down")

    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    with pytest.raises(Exception, match="transport exception"):
        TurnDriver(rnd, Explodes()).step()
    assert selfplay._state_snapshot(rnd.rnd) == before
    assert rnd.failed is not None


@pytest.mark.parametrize("binding", ["packet", "memory", "provider"])
def test_packet_memory_and_provider_bindings_fail_at_driver_wiring(binding):
    rnd = game()
    before = selfplay._state_snapshot(rnd.rnd)
    class BoundWrong:
        def call(self, packet):
            values = {
                "team": packet.team,
                "packet_sha256": packet.sha256,
                "memory_sha256": packet.memory.sha256,
                "provider_request_sha256": packet.sha256,
                "provider_response_sha256": "f" * 64,
            }
            if binding == "packet":
                values["packet_sha256"] = "0" * 64
            elif binding == "memory":
                values["memory_sha256"] = "0" * 64
            else:
                values["provider_response_sha256"] = None
            return PlannerResponse(
                Intent("play", packet.decision_sha256, candidate_index=0,
                       confidence="low", planning_note="bound"),
                usage(), **values)
    with pytest.raises(TurnValidationError):
        TurnDriver(rnd, BoundWrong()).run(max_decisions=1)
    assert selfplay._state_snapshot(rnd.rnd) == before


def test_fake_two_team_game_completes_and_private_artifacts_reopen(tmp_path):
    rnd = game()
    fake = Fake()
    from shengji.luna.journal import FileTurnJournal
    journal = FileTurnJournal(tmp_path / "journal")
    rows = TurnDriver(rnd, fake, journal=journal).run()
    assert rnd.complete and rnd.failed is None
    assert {row.team for row in rows} == {0, 1}
    assert fake.max_concurrent == 1
    artifacts = rnd.completed_artifacts()
    reopened = selfplay.SealedTrajectory.reopen(
        artifacts.trajectory.private_bytes())
    selfplay.CompletedGameArtifacts(reopened, artifacts.terminal_receipt)
    assert journal.summary()["committed_call_count"] == len(rows)


def test_forced_only_game_makes_zero_calls(monkeypatch):
    rnd = game()
    calls = []
    # The constructor's forced advancement is the production behavior.  Make
    # the remaining ballot forced as a compact zero-RPC witness.
    original = rnd._candidates
    monkeypatch.setattr(rnd, "_candidates", lambda seat: [original(seat)[0]])
    rnd._advance_forced()
    class Never:
        def call(self, packet):
            calls.append(packet)
            raise AssertionError("forced move called transport")
    TurnDriver(rnd, Never()).run()
    assert calls == []

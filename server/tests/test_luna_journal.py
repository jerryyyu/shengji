"""Crash-boundary and reopen witnesses for the PT-Luna turn journal."""

from __future__ import annotations

import hashlib

import pytest

from shengji.luna import game as selfplay
from shengji.luna import atomic_io as rpc_io
from shengji.luna.journal import (
    FileTurnJournal,
    TurnJournalError,
)
from shengji.luna.turn import (
    DecisionPacket,
    Intent,
    PhaseContext,
    PlannerResponse,
    TeamMemory,
    TurnDriver,
    Usage,
)


SECRET = hashlib.sha256(b"pt-luna-journal-tests-v1").digest()
COORDINATE = ("2", 0, 0)


def game():
    return selfplay.LunaSelfPlayGame(
        selfplay.build_root(SECRET, COORDINATE),
        coordinate=COORDINATE, seed_secret=SECRET)


def response(packet, *, index=0):
    return PlannerResponse(
        Intent("play", packet.decision_sha256, candidate_index=index,
               confidence="low", planning_note="hold entries"),
        Usage(10, 2, 12, 1), 0, packet.team, packet.sha256,
        packet.memory.sha256, packet.sha256, "f" * 64)


class Fake:
    def __init__(self, *, index=0, explode=False):
        self.index = index
        self.explode = explode
        self.calls = 0

    def call(self, packet):
        self.calls += 1
        if self.explode:
            raise RuntimeError("provider vanished")
        return response(packet, index=self.index)


def first_packet(rnd):
    team = rnd.acting_team
    assert team in (0, 1)
    observation = rnd.session(team).observe()
    memory = TeamMemory.initial(team, selfplay._state_digest(rnd.rnd, team))
    return DecisionPacket.from_observation(
        observation, coordinate=COORDINATE, mirror=0, team=team,
        decision_index=0, memory=memory, phase=PhaseContext())


def test_committed_transition_reopens_and_replays_without_model_call(tmp_path):
    original = game()
    journal = FileTurnJournal(tmp_path / "journal")
    fake = Fake()
    TurnDriver(original, fake, journal=journal).run(max_decisions=1)
    expected = selfplay._state_snapshot(original.rnd)
    assert fake.calls == 1
    assert journal.summary() == {
        "schema": "pt-luna-turn-journal-summary-v1", "call_count": 1,
        "opened_rpc_count": 1, "committed_decision_count": 1,
        "committed_call_count": 1, "refused_call_count": 0,
        "private_evidence_count": 0,
        "pending_stages": None}
    assert journal.usage_totals() == {
        "input_tokens": 10, "cached_input_tokens": 0,
        "cache_write_input_tokens": 0, "output_tokens": 2,
        "reasoning_output_tokens": 0, "total_tokens": 12,
        "wall_ms": 1, "response_count": 1}

    reopened = game()
    never = Fake(explode=True)
    driver = TurnDriver(
        reopened, never, journal=FileTurnJournal(tmp_path / "journal"))
    assert len(driver.evidence) == 1
    driver.run(max_decisions=1)
    assert never.calls == 0
    assert selfplay._state_snapshot(reopened.rnd) == expected


def test_rollout_phase_plan_survives_play_commit_and_journal_reopen(tmp_path):
    class Phased:
        calls = 0
        def call(self, packet):
            self.calls += 1
            if packet.phase.phase <= 2:
                intent = Intent(
                    "rollout", packet.decision_sha256,
                    candidate_indices=(0,), continuations=("smart-all",),
                    planning_note=f"phase-{packet.phase.phase}")
            else:
                intent = Intent(
                    "play", packet.decision_sha256, candidate_index=0,
                    confidence="low", planning_note="")
            return PlannerResponse(
                intent, Usage(10, 2, 12, 1), 0, packet.team,
                packet.sha256, packet.memory.sha256,
                packet.sha256, "f" * 64)
    evaluate = lambda team, index, continuation: {
        "candidate_index": index, "continuation": continuation,
        "rollout_points": 80, "team_signed_level_utility": 1}
    original = game()
    original.evaluate = evaluate
    journal = FileTurnJournal(tmp_path / "journal")
    team = original.acting_team
    driver = TurnDriver(original, Phased(), journal=journal)
    driver.run(max_decisions=1)
    assert driver._memories[team].strategy_note == "phase-2"

    reopened = game()
    reopened.evaluate = evaluate
    replay = TurnDriver(
        reopened, Fake(explode=True),
        journal=FileTurnJournal(tmp_path / "journal"))
    assert replay._memories[team].strategy_note == "phase-2"


def test_response_sealed_before_commit_is_reused_exactly_once(tmp_path):
    original = game()
    journal = FileTurnJournal(tmp_path / "journal")
    packet = first_packet(original)
    first = Fake()
    sealed = journal.call(packet, first)
    assert sealed.intent.candidate_index == 0 and first.calls == 1
    assert journal.summary()["pending_stages"] == ["open", "response"]

    reopened = game()
    never = Fake(explode=True)
    TurnDriver(
        reopened, never,
        journal=FileTurnJournal(tmp_path / "journal")).run(max_decisions=1)
    assert never.calls == 0
    assert FileTurnJournal(tmp_path / "journal").summary()[
        "committed_call_count"] == 1


def test_process_death_before_response_link_recovers_without_second_call(
        tmp_path, monkeypatch):
    class ProcessDeath(BaseException):
        pass

    real_link = rpc_io.os.link
    died = False

    def die_on_response(source, destination, **kwargs):
        nonlocal died
        if not died and str(destination).endswith("-response.json"):
            died = True
            raise ProcessDeath()
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(rpc_io.os, "link", die_on_response)
    first = Fake()
    with pytest.raises(ProcessDeath):
        FileTurnJournal(tmp_path / "journal").call(
            first_packet(game()), first)
    assert first.calls == 1

    never = Fake(explode=True)
    TurnDriver(
        game(), never, journal=FileTurnJournal(tmp_path / "journal")
    ).run(max_decisions=1)
    assert never.calls == 0
    assert FileTurnJournal(tmp_path / "journal").summary()[
        "committed_call_count"] == 1


def test_process_death_after_response_link_recovers_without_second_call(
        tmp_path, monkeypatch):
    class ProcessDeath(BaseException):
        pass

    real_link = rpc_io.os.link
    real_fsync = rpc_io._fsync_dir
    linked_response = False
    died = False

    def observe_response_link(source, destination, **kwargs):
        nonlocal linked_response
        value = real_link(source, destination, **kwargs)
        if str(destination).endswith("-response.json"):
            linked_response = True
        return value

    def die_after_response_link(path):
        nonlocal died
        if linked_response and not died:
            died = True
            raise ProcessDeath()
        return real_fsync(path)

    monkeypatch.setattr(rpc_io.os, "link", observe_response_link)
    monkeypatch.setattr(rpc_io, "_fsync_dir", die_after_response_link)
    first = Fake()
    with pytest.raises(ProcessDeath):
        FileTurnJournal(tmp_path / "journal").call(
            first_packet(game()), first)
    assert first.calls == 1

    never = Fake(explode=True)
    TurnDriver(
        game(), never, journal=FileTurnJournal(tmp_path / "journal")
    ).run(max_decisions=1)
    assert never.calls == 0
    assert FileTurnJournal(tmp_path / "journal").summary()[
        "committed_call_count"] == 1


def test_known_transport_refusal_is_sealed_and_never_retried(tmp_path):
    original = game()
    journal = FileTurnJournal(tmp_path / "journal")
    with pytest.raises(TurnJournalError, match="transport exception"):
        journal.call(first_packet(original), Fake(explode=True))
    assert journal.summary() == {
        "schema": "pt-luna-turn-journal-summary-v1", "call_count": 1,
        "opened_rpc_count": 1, "committed_decision_count": 0,
        "committed_call_count": 0, "refused_call_count": 1,
        "private_evidence_count": 0,
        "pending_stages": ["open", "refusal"]}

    reopened = game()
    never = Fake()
    with pytest.raises(TurnJournalError, match="previously refused"):
        TurnDriver(
            reopened, never,
            journal=FileTurnJournal(tmp_path / "journal")).run(max_decisions=1)
    assert never.calls == 0


def test_process_death_after_open_remains_ambiguous_and_never_retried(tmp_path):
    class ProcessDeath(BaseException):
        pass

    class Dies:
        def call(self, packet):
            del packet
            raise ProcessDeath()

    journal = FileTurnJournal(tmp_path / "journal")
    with pytest.raises(ProcessDeath):
        journal.call(first_packet(game()), Dies())
    assert journal.summary()["pending_stages"] == ["open"]
    with pytest.raises(TurnJournalError, match="disposition unknown"):
        TurnDriver(
            game(), Fake(), journal=FileTurnJournal(tmp_path / "journal")
        ).run(max_decisions=1)


def test_invalid_sealed_response_cannot_mutate_or_be_replaced(tmp_path):
    original = game()
    before = selfplay._state_snapshot(original.rnd)
    bad = Fake(index=999)
    driver = TurnDriver(
        original, bad, journal=FileTurnJournal(tmp_path / "journal"))
    with pytest.raises(Exception, match="outside ballot"):
        driver.run(max_decisions=1)
    assert selfplay._state_snapshot(original.rnd) == before
    assert FileTurnJournal(tmp_path / "journal").summary()[
        "pending_stages"] == ["open", "response"]

    with pytest.raises(Exception, match="outside ballot"):
        TurnDriver(
            game(), Fake(), journal=FileTurnJournal(tmp_path / "journal")
        ).run(max_decisions=1)


def test_committed_call_cannot_be_committed_twice(tmp_path):
    rnd = game()
    journal = FileTurnJournal(tmp_path / "journal")
    driver = TurnDriver(rnd, Fake(), journal=journal)
    rows = driver.run(max_decisions=1)
    assert len(rows) == 1
    with pytest.raises(TurnJournalError, match="not pending"):
        journal.commit(rows[0])

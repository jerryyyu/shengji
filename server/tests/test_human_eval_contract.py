import asyncio
import json
import random
from types import SimpleNamespace

import pytest

from shengji.api.human_eval import (
    HumanEvaluationContext,
    HumanEvaluationError,
    blocked_arm,
    derive_participant_pair_id,
)


def _context(**changes):
    values = {
        "experiment_id": "human-c1-pilot-v1",
        "session_id": "session-0001",
        "participant_ids_by_human_seat": ("b" * 32, "c" * 32),
        "cohort_id": "experienced-v1",
        "consent_version": "consent-v1",
        "block_id": "pair-block-0001",
        "block_slot": 0,
        "arm": "candidate",
        "candidate_policy": "candidate-policy",
        "candidate_git": "d" * 40,
        "candidate_image_sha256": "e" * 64,
        "champion_policy": "mc-s0-report-lcb",
        "champion_git": "f" * 40,
        "champion_image_sha256": "1" * 64,
        "candidate_ballot_id": "s3a-structured-bury-v1",
        "champion_ballot_id": "report-lcb-ballot-v1",
    }
    values["participant_pair_id"] = derive_participant_pair_id(
        values["participant_ids_by_human_seat"])
    values.update(changes)
    return HumanEvaluationContext(**values)


def test_block_schedule_is_deterministic_and_complementary():
    participants = ("b" * 32, "c" * 32)
    kwargs = {
        "assignment_secret": b"x" * 32,
        "participant_pair_id": derive_participant_pair_id(participants),
        "block_id": "pair-block-0001",
    }
    first = blocked_arm(**kwargs, block_slot=0)
    second = blocked_arm(**kwargs, block_slot=1)

    assert {first, second} == {"candidate", "champion"}
    assert blocked_arm(**kwargs, block_slot=0) == first


@pytest.mark.parametrize("changes,match", [
    ({"participant_ids_by_human_seat": ("b" * 32, "b" * 32)},
     "two distinct"),
    ({"candidate_git": "dirty"}, "candidate_git"),
    ({"candidate_image_sha256": "e" * 63}, "candidate_image"),
    ({"block_slot": True}, "block_slot"),
    ({"participant_pair_id": "a" * 32}, "participant_pair_id"),
    ({"candidate_policy": "mc-s0-report-lcb"}, "must differ"),
])
def test_context_refuses_ambiguous_identity(changes, match):
    with pytest.raises(HumanEvaluationError, match=match):
        _context(**changes)


def test_payload_is_complete_evaluation_only_and_server_side():
    payload = _context().log_payload()

    assert payload["human_seats"] == [0, 2]
    assert payload["bot_seats"] == [1, 3]
    assert payload["assignment_probability"] == 0.5
    assert payload["active_policy"] == "candidate-policy"
    assert payload["candidate"]["ballot_id"] == "s3a-structured-bury-v1"
    assert payload["champion"]["ballot_id"] == "report-lcb-ballot-v1"
    assert payload["training_excluded"] is True
    assert payload["candidate_selection_excluded"] is True
    assert payload["production_promotion_gate"] is True
    assert payload["policy_hidden_from_players"] is True


def test_room_writes_evaluation_only_to_separate_root(tmp_path, monkeypatch):
    from shengji.api import server

    ordinary = tmp_path / "ordinary"
    evaluation = tmp_path / "evaluation"
    monkeypatch.setattr(server, "LOG_DIR", ordinary)
    room = server.Room(
        code="EVAL", log_dir=evaluation, evaluation=_context(),
        bot=SimpleNamespace(policy_name="candidate-policy"))

    room.log_event("probe", value=1)

    assert not ordinary.exists()
    record = json.loads((evaluation / "EVAL.jsonl").read_text())
    assert record["training_excluded"] is True
    assert record["experiment"]["schema"] == "human-vs-bot-evaluation-v1"
    assert record["experiment"]["active_policy"] == "candidate-policy"


def test_evaluation_room_refuses_ordinary_training_root(tmp_path, monkeypatch):
    from shengji.api import server

    ordinary = tmp_path / "ordinary"
    monkeypatch.setattr(server, "LOG_DIR", ordinary)

    with pytest.raises(ValueError, match="disjoint log root"):
        server.Room(
            code="EVAL", log_dir=ordinary, evaluation=_context(),
            bot=SimpleNamespace(policy_name="candidate-policy"))


def test_evaluation_room_refuses_policy_log_misattribution(tmp_path, monkeypatch):
    from shengji.api import server

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")

    with pytest.raises(ValueError, match="policy identity"):
        server.Room(
            code="EVAL", log_dir=tmp_path / "evaluation",
            evaluation=_context(),
            bot=SimpleNamespace(policy_name="mc-s0-report-lcb"))


def test_evaluation_room_refuses_nested_training_root(tmp_path, monkeypatch):
    from shengji.api import server

    ordinary = tmp_path / "ordinary"
    monkeypatch.setattr(server, "LOG_DIR", ordinary)

    with pytest.raises(ValueError, match="disjoint log root"):
        server.Room(
            code="EVAL", log_dir=ordinary / "evaluation",
            evaluation=_context(),
            bot=SimpleNamespace(policy_name="candidate-policy"))


def test_evaluation_logging_failure_is_not_silenced(tmp_path, monkeypatch):
    from shengji.api import server

    ordinary = tmp_path / "ordinary"
    evaluation = tmp_path / "evaluation"
    evaluation.write_text("not a directory")
    monkeypatch.setattr(server, "LOG_DIR", ordinary)
    room = server.Room(
        code="EVAL", log_dir=evaluation, evaluation=_context(),
        bot=SimpleNamespace(policy_name="candidate-policy"))

    with pytest.raises(OSError):
        room.log_event("probe")
    assert room.evaluation_invalidated is True


def test_evaluation_start_logging_failure_terminally_invalidates_room(
        tmp_path, monkeypatch):
    from shengji.api import server

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    # Construct the room first, then make its dedicated log root unwritable as
    # a directory.  start_game must fail before launching deal/watchdog tasks.
    room.log_dir.write_text("not a directory")

    async def scenario():
        with pytest.raises(OSError):
            await server.handle_action(room, 0, {"type": "start_game"})

        assert room.evaluation_invalidated is True
        assert room.deal_task is None
        assert room.watchdog_task is None
        with pytest.raises(server.IllegalPlay, match="invalidated"):
            await server.handle_action(room, 0, {"type": "start_game"})

    asyncio.run(scenario())


def _evaluation_room(server, tmp_path):
    context = _context()
    participants = context.participant_ids_by_human_seat
    return server.Room(
        code="EVAL", log_dir=tmp_path / "evaluation", evaluation=context,
        bot=SimpleNamespace(policy_name="candidate-policy"),
        seats=[
            server.Seat(
                name="Human A", connected=True,
                evaluation_participant_id=participants[0]),
            server.Seat(name="Bot 1", is_bot=True),
            server.Seat(
                name="Human B", connected=True,
                evaluation_participant_id=participants[1]),
            server.Seat(name="Bot 3", is_bot=True),
        ],
    )


def test_evaluation_start_accepts_only_bound_two_human_team(tmp_path,
                                                            monkeypatch):
    from shengji.api import server

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)

    server.validate_human_evaluation_start(room)


def test_evaluation_log_omits_names_and_chat_content(tmp_path, monkeypatch):
    from shengji.api import server
    from shengji.engine.game import Game

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    room.game = Game(random.Random(7))
    room.game.start_round()
    server._log_round_start(room)
    room.log_event("chat", seat=0, text="personally identifying text", bot=False)

    records = [json.loads(line) for line in
               (tmp_path / "evaluation" / "EVAL.jsonl").read_text().splitlines()]
    start, chat = records
    assert all("name" not in player for player in start["players"])
    assert [player.get("participant_id") for player in start["players"]
            if not player["is_bot"]] == list(
                room.evaluation.participant_ids_by_human_seat)
    assert "text" not in chat
    assert chat["content_recorded"] is False


@pytest.mark.parametrize("mutate,match", [
    (lambda room: setattr(room.seats[0], "connected", False),
     "connected humans"),
    (lambda room: setattr(room.seats[2], "evaluation_participant_id", "a" * 32),
     "identity mismatch"),
    (lambda room: setattr(room.seats[3], "is_bot", False),
     "bots at seats"),
])
def test_evaluation_start_refuses_layout_or_identity_drift(
        tmp_path, monkeypatch, mutate, match):
    from shengji.api import server

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    mutate(room)

    with pytest.raises(server.IllegalPlay, match=match):
        server.validate_human_evaluation_start(room)

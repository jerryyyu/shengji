import asyncio
import hashlib
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.api.human_eval import (
    ConsentedParticipant,
    HumanEvaluationDesign,
    HumanEvaluationContext,
    HumanEvaluationError,
    PolicyIdentity,
    blocked_arm,
    construct_reviewed_assignment,
    derive_participant_pair_id,
    registered_policy_ballot_id,
    reserve_assignment_once,
    reopen_assigned_policy,
    reopen_assigned_policy_from_receipt,
)


def _context(**changes):
    values = {
        "experiment_id": "human-c1-pilot-v1",
        "assignment_design_sha256": "a" * 64,
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


def _design():
    return HumanEvaluationDesign(
        experiment_id="human-c1-pilot-v1",
        assignment_design_sha256="a" * 64,
        cohort_id="experienced-v1",
        consent_version="consent-v1",
        candidate=PolicyIdentity(
            policy="candidate-policy", git="d" * 40,
            image_sha256="e" * 64,
            ballot_id="s3a-structured-bury-v1"),
        champion=PolicyIdentity(
            policy="mc-s0-report-lcb", git="f" * 40,
            image_sha256="1" * 64,
            ballot_id="report-lcb-ballot-v1"),
    )


def _participants(**changes):
    values = [
        {
            "participant_id": "b" * 32,
            "cohort_id": "experienced-v1",
            "consent_version": "consent-v1",
            "opted_in": True,
        },
        {
            "participant_id": "c" * 32,
            "cohort_id": "experienced-v1",
            "consent_version": "consent-v1",
            "opted_in": True,
        },
    ]
    for key, value in changes.items():
        index_text, field = key.split("__", 1)
        values[int(index_text)][field] = value
    return tuple(ConsentedParticipant(**value) for value in values)


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
    assert payload["assignment_design_sha256"] == "a" * 64
    assert payload["bot_seats"] == [1, 3]
    assert payload["assignment_probability"] == 0.5
    assert payload["active_policy"] == "candidate-policy"
    assert payload["candidate"]["ballot_id"] == "s3a-structured-bury-v1"
    assert payload["champion"]["ballot_id"] == "report-lcb-ballot-v1"
    assert payload["training_excluded"] is True
    assert payload["candidate_selection_excluded"] is True
    assert payload["production_promotion_gate"] is True
    assert payload["policy_hidden_from_players"] is True


def test_reviewed_assignment_derives_hidden_complementary_arms_and_sessions():
    common = {
        "design": _design(),
        "participants_by_human_seat": _participants(),
        "block_id": "pair-block-0001",
        "assignment_secret": b"x" * 32,
    }
    first = construct_reviewed_assignment(**common, block_slot=0)
    second = construct_reviewed_assignment(**common, block_slot=1)
    replay = construct_reviewed_assignment(**common, block_slot=0)

    assert {first.arm, second.arm} == {"candidate", "champion"}
    assert first.session_id != second.session_id
    assert replay == first
    assert first.participant_pair_id == second.participant_pair_id
    assert first.assignment_design_sha256 == "a" * 64
    assert first.log_payload()["assignment_probability"] == 0.5


def test_reviewed_design_digest_domains_session_identity():
    common = {
        "participants_by_human_seat": _participants(),
        "block_id": "pair-block-0001",
        "block_slot": 0,
        "assignment_secret": b"x" * 32,
    }
    first = construct_reviewed_assignment(design=_design(), **common)
    second_design = replace(
        _design(), assignment_design_sha256="2" * 64)
    second = construct_reviewed_assignment(design=second_design, **common)

    assert first.session_id != second.session_id


@pytest.mark.parametrize("participants,match", [
    (lambda: _participants(**{"0__cohort_id": "site-average"}), "cohort"),
    (lambda: _participants(**{"1__consent_version": "old-consent"}),
     "consent version"),
    (lambda: _participants(**{"1__participant_id": "b" * 32}),
     "two distinct"),
])
def test_reviewed_assignment_refuses_participant_design_drift(participants,
                                                               match):
    with pytest.raises(HumanEvaluationError, match=match):
        construct_reviewed_assignment(
            design=_design(), participants_by_human_seat=participants(),
            block_id="pair-block-0001", block_slot=0,
            assignment_secret=b"x" * 32)


def test_consent_fact_refuses_false_or_truthy_opt_in():
    with pytest.raises(HumanEvaluationError, match="not opted in"):
        ConsentedParticipant(
            participant_id="b" * 32, cohort_id="experienced-v1",
            consent_version="consent-v1", opted_in=1)


def _registered_context(**changes):
    values = {
        "candidate_policy": "mc-strong",
        "candidate_ballot_id": registered_policy_ballot_id("mc-strong"),
        "champion_policy": "mc-s0-report-lcb",
        "champion_ballot_id": registered_policy_ballot_id(
            "mc-s0-report-lcb"),
    }
    values.update(changes)
    return _context(**values)


@pytest.mark.parametrize("arm", ["candidate", "champion"])
def test_runtime_reopens_exact_registered_assigned_policy(arm):
    context = _registered_context(arm=arm)
    expected = context.active_policy_identity

    bot = reopen_assigned_policy(
        context, runtime_git=expected.git,
        runtime_image_sha256=expected.image_sha256)

    assert bot.policy_name == expected.policy


@pytest.mark.parametrize("changes,runtime_git,runtime_image,match", [
    ({}, "0" * 40, "e" * 64, "Git"),
    ({}, "d" * 40, "0" * 64, "image"),
    ({"candidate_ballot_id": "wrong-ballot-v1"},
     "d" * 40, "e" * 64, "ballot"),
    ({"candidate_policy": "not-registered-policy",
      "candidate_ballot_id": "not-registered-ballot"},
     "d" * 40, "e" * 64, "cannot reopen"),
])
def test_runtime_policy_reopen_fails_closed(changes, runtime_git,
                                            runtime_image, match):
    context = _registered_context(**changes)
    with pytest.raises(HumanEvaluationError, match=match):
        reopen_assigned_policy(
            context, runtime_git=runtime_git,
            runtime_image_sha256=runtime_image)


def _runtime_receipt(context):
    return {
        "schema": "human-evaluation-runtime-identity-receipt-v1",
        "assignment_design_sha256": context.assignment_design_sha256,
        "policy": {
            "policy": context.active_policy_identity.policy,
            "git": context.active_policy_identity.git,
            "image_sha256": context.active_policy_identity.image_sha256,
            "ballot_id": context.active_policy_identity.ballot_id,
        },
        "identity_only": True,
        "human_traffic_authorized": False,
    }


def _write_runtime_receipt(path, receipt):
    raw = json.dumps(receipt, sort_keys=True).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_runtime_receipt_reopens_exact_policy_without_granting_traffic(
        tmp_path):
    context = _registered_context()
    path = tmp_path / "runtime-receipt.json"
    digest = _write_runtime_receipt(path, _runtime_receipt(context))

    bot = reopen_assigned_policy_from_receipt(
        context, receipt_path=path, expected_receipt_sha256=digest)

    assert bot.policy_name == context.active_policy


@pytest.mark.parametrize("mutate,match", [
    (lambda receipt: receipt.update(
        assignment_design_sha256="2" * 64), "design"),
    (lambda receipt: receipt.update(
        human_traffic_authorized=True), "authority"),
    (lambda receipt: receipt["policy"].update(
        ballot_id="wrong-ballot-v1"), "policy identity"),
    (lambda receipt: receipt.update(extra="ambiguous"), "fields"),
])
def test_runtime_receipt_refuses_identity_or_authority_drift(
        tmp_path, mutate, match):
    context = _registered_context()
    receipt = _runtime_receipt(context)
    mutate(receipt)
    path = tmp_path / "runtime-receipt.json"
    digest = _write_runtime_receipt(path, receipt)

    with pytest.raises(HumanEvaluationError, match=match):
        reopen_assigned_policy_from_receipt(
            context, receipt_path=path,
            expected_receipt_sha256=digest)


def test_runtime_receipt_refuses_wrong_digest_symlink_and_hardlink(tmp_path):
    context = _registered_context()
    original = tmp_path / "runtime-receipt.json"
    digest = _write_runtime_receipt(original, _runtime_receipt(context))

    with pytest.raises(HumanEvaluationError, match="digest mismatch"):
        reopen_assigned_policy_from_receipt(
            context, receipt_path=original,
            expected_receipt_sha256="0" * 64)

    symlink = tmp_path / "runtime-receipt-symlink.json"
    symlink.symlink_to(original)
    with pytest.raises(HumanEvaluationError, match="regular unlinked"):
        reopen_assigned_policy_from_receipt(
            context, receipt_path=symlink,
            expected_receipt_sha256=digest)

    hardlink = tmp_path / "runtime-receipt-hardlink.json"
    os.link(original, hardlink)
    with pytest.raises(HumanEvaluationError, match="regular unlinked"):
        reopen_assigned_policy_from_receipt(
            context, receipt_path=hardlink,
            expected_receipt_sha256=digest)


def test_assignment_reservation_is_identity_only_and_secret_independent(
        tmp_path):
    context = _registered_context()
    reservation = reserve_assignment_once(context, ledger_root=tmp_path)
    record = json.loads(Path(reservation["path"]).read_text())

    assert record["assignment_slot_id"] == \
        reservation["assignment_slot_id"]
    assert record["session_id"] == context.session_id
    assert record["participant_pair_id"] == context.participant_pair_id
    assert record["human_traffic_authorized"] is False
    assert record["training_authorized"] is False
    assert record["production_promotion"] is False
    assert "participant_ids_by_human_seat" not in record


def test_assignment_reservation_refuses_reissue_even_if_session_changes(
        tmp_path):
    context = _registered_context()
    reserve_assignment_once(context, ledger_root=tmp_path)
    changed_session = replace(context, session_id="session-different")

    with pytest.raises(HumanEvaluationError, match="already reserved"):
        reserve_assignment_once(changed_session, ledger_root=tmp_path)


def test_assignment_reservation_is_atomic_under_concurrent_issuance(tmp_path):
    context = _registered_context()

    def attempt():
        try:
            return reserve_assignment_once(context, ledger_root=tmp_path)
        except HumanEvaluationError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))

    assert sum(isinstance(result, dict) for result in results) == 1
    failures = [result for result in results
                if isinstance(result, HumanEvaluationError)]
    assert len(failures) == 1
    assert "already reserved" in str(failures[0])


def test_assignment_reservation_refuses_symlink_ledger_root(tmp_path):
    context = _registered_context()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(HumanEvaluationError, match="real existing directory"):
        reserve_assignment_once(context, ledger_root=link)


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


def test_bound_participant_disconnect_terminally_invalidates_session(
        tmp_path, monkeypatch):
    from shengji.api import server
    from shengji.engine.game import Game

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    room.game = Game(random.Random(7))
    room.game.start_round()
    seat = room.seats[0]

    server._detach(seat, room, seat.gen)

    assert room.evaluation_invalidated is True
    assert seat.connected is False
    records = [json.loads(line) for line in
               (tmp_path / "evaluation" / "EVAL.jsonl").read_text().splitlines()]
    assert records == [{
        **{key: records[0][key] for key in ("t", "room", "round")},
        "e": "evaluation_invalidated",
        "seat": 0,
        "reason": "participant_disconnect",
        "terminal": True,
        "experiment": room.evaluation.log_payload(),
        "training_excluded": True,
    }]
    assert "name" not in records[0]


def test_stale_disconnect_cannot_invalidate_live_evaluation_session(
        tmp_path, monkeypatch):
    from shengji.api import server
    from shengji.engine.game import Game

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    room.game = Game(random.Random(7))
    room.game.start_round()
    seat = room.seats[0]

    server._detach(seat, room, seat.gen - 1)

    assert room.evaluation_invalidated is False
    assert seat.connected is True
    assert not (tmp_path / "evaluation" / "EVAL.jsonl").exists()


def test_disconnect_log_failure_still_detaches_and_invalidates(
        tmp_path, monkeypatch):
    from shengji.api import server
    from shengji.engine.game import Game

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    room.game = Game(random.Random(7))
    room.game.start_round()
    room.log_dir.write_text("not a directory")
    seat = room.seats[0]

    server._detach(seat, room, seat.gen)

    assert room.evaluation_invalidated is True
    assert seat.connected is False
    assert seat.ws is None


def test_disconnect_after_completed_game_does_not_invalidate_evidence(
        tmp_path, monkeypatch):
    from shengji.api import server
    from shengji.engine.game import Game

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    room.game = Game(random.Random(7))
    room.game.start_round()
    room.game.game_over = True
    seat = room.seats[0]

    server._detach(seat, room, seat.gen)

    assert room.evaluation_invalidated is False
    assert seat.connected is False


def test_invalidated_evaluation_refuses_bot_and_takeover_progress(
        tmp_path, monkeypatch):
    from shengji.api import server

    monkeypatch.setattr(server, "LOG_DIR", tmp_path / "ordinary")
    room = _evaluation_room(server, tmp_path)
    room.evaluation_invalidated = True
    monkeypatch.setattr(server, "current_actor", lambda _room: 1)
    assert server._turn_eligible(room, 1, "bot") is False

    room.seats[0].connected = False
    room.seats[0].left_at = server.now() - server.TAKEOVER_AFTER - 1
    monkeypatch.setattr(server, "current_actor", lambda _room: 0)
    assert server._turn_eligible(room, 0, "takeover") is False

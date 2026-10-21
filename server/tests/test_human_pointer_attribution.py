"""Synthetic end-to-end checks for human_v8 source-event attribution."""

import hashlib
import json
import random
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import Round, actual_play_after
from shengji.harvest import human
from shengji.harvest.common import InputRegistry, pseudonym
from shengji.harvest.manifest import write_source
from shengji.harvest.rebuild import engine_level_change, round_from_setup
from shengji.harvest.room_log import extract_round, extract_room_logs, read_rounds
from shengji.harvest.schema import validate_record


_MISSING = object()


def _event(round_no, kind, **fields):
    return {"round": round_no, "e": kind, **fields}


def _completed_round():
    round_no = 1
    rnd = Round("4", 0, random.Random(731))
    players = [
        {"seat": 0, "name": "Alice", "is_bot": False},
        {"seat": 1, "name": "Bot 1", "is_bot": True},
        {"seat": 2, "name": "Bot 2", "is_bot": True},
        {"seat": 3, "name": "Bot 3", "is_bot": True},
    ]
    events = [_event(
        round_no, "round_start", deck=list(rnd.deck), banker=rnd.banker,
        trump_rank=rnd.trump_rank, levels=["4"] * 4, players=players)]
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    events.append(_event(
        round_no, "trump", suit=rnd.trump_suit, rank=rnd.trump_rank,
        banker=rnd.banker, declared=False))

    bot = HeuristicBot()
    bury = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, bury)
    events.append(_event(
        round_no, "bury", seat=rnd.banker, cards=bury, bot=False))

    first = True
    while rnd.phase == "play":
        seat = rnd.turn
        cards = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, cards)
        played = actual_play_after(rnd, seat, previous_last)
        events.append(_event(
            round_no, "play", seat=seat, cards=played, bot=(not first)))
        first = False
    events.append(_event(
        round_no, "round_end", attacker_points=rnd.attacker_points,
        kitty=list(rnd.buried), kitty_points=rnd.kitty_bonus,
        winner_team=(1 - rnd.banker % 2) if rnd.attacker_points >= 80
        else rnd.banker % 2,
        level_change=engine_level_change(rnd.attacker_points),
        new_levels=["4"] * 4, next_banker=rnd.banker, game_over=False))
    return events


def _write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _fixture(tmp_path, *, play_bot=False, bury_bot=False):
    events = _completed_round()
    play_index = next(i for i, event in enumerate(events)
                      if event["e"] == "play")
    bury_index = next(i for i, event in enumerate(events)
                      if event["e"] == "bury")
    for index, marker in ((play_index, play_bot), (bury_index, bury_bot)):
        if marker is _MISSING:
            events[index].pop("bot")
        else:
            events[index]["bot"] = marker

    logs = tmp_path / "logs"
    logs.mkdir()
    source = logs / "ROOM.jsonl"
    _write_jsonl(source, events)

    registry = InputRegistry()
    rounds, bad_lines = read_rounds(source, registry)
    assert bad_lines == 0
    records, _ = extract_round("logs/ROOM.jsonl", 1, rounds[1],
                               fallback_policy=None)
    play_record = next(r for r in records if r["decision_kind"] == "play")
    bury_record = next(r for r in records if r["decision_kind"] == "bury")
    event_index = int(play_record["source_ref"].rsplit(":event-", 1)[1])
    pre_bury = round_from_setup(
        bury_record["deck"], bury_record["setup"], stop_before_bury=True)

    corpus = tmp_path / "human_v8"
    corpus.mkdir()
    _write_jsonl(corpus / "play_decisions.jsonl", [{
        "source": "ROOM.jsonl", "round": 1, "event_index": event_index,
        "seat": play_record["seat"], "chosen": sorted(play_record["action"]),
        "player_id": pseudonym("Alice"),
    }])
    _write_jsonl(corpus / "bury_decisions.jsonl", [{
        "source": "ROOM.jsonl", "round": 1, "seat": bury_record["seat"],
        "hand_before": sorted(pre_bury.hands[pre_bury.banker]),
        "chosen": sorted(bury_record["action"]),
        "player_id": pseudonym("Alice"),
    }])
    manifest = {
        "schema": "human-decision-corpus-v1",
        "training_authorized": False,
        "strength_claim": False,
        "allowed_use": ["offline-analysis"],
        "run_id": "synthetic-human-pointer-test",
        "sources": [{"name": "ROOM.jsonl",
                     "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
    }
    (corpus / "manifest.json").write_text(json.dumps(manifest))
    return corpus


def test_valid_human_play_and_bury_are_finalized(tmp_path):
    result = human.extract_human(human_dir=_fixture(tmp_path),
                                 registry=InputRegistry(), repo=tmp_path)

    assert {record["decision_kind"] for record in result.public} == {"play", "bury"}
    assert all(record["source"] == "human" for record in result.public)
    for record in result.public:
        validate_record(record)


@pytest.mark.parametrize("kind", ["play", "bury"])
def test_bot_takeover_with_human_roster_is_rejected(tmp_path, kind):
    kwargs = {f"{kind}_bot": True}
    corpus = _fixture(tmp_path, **kwargs)

    with pytest.raises(human.HumanPointerError,
                       match=rf"{kind} pointer .*exactly false"):
        human.extract_human(human_dir=corpus, registry=InputRegistry(),
                            repo=tmp_path)


@pytest.mark.parametrize("kind", ["play", "bury"])
@pytest.mark.parametrize("marker", [_MISSING, None, "false", 0, 1])
def test_missing_or_nonboolean_bot_flag_is_rejected(tmp_path, kind, marker):
    kwargs = {f"{kind}_bot": marker}
    corpus = _fixture(tmp_path, **kwargs)

    with pytest.raises(human.HumanPointerError,
                       match=rf"{kind} pointer .*exactly false"):
        human.extract_human(human_dir=corpus, registry=InputRegistry(),
                            repo=tmp_path)


def _play_events(events):
    return [event for event in events if event["e"] == "play"]


def _summary_for(tmp_path, events):
    source = tmp_path / "logs" / "ROOM.jsonl"
    source.parent.mkdir()
    _write_jsonl(source, events)
    result = extract_room_logs(files=[source], registry=InputRegistry(),
                               repo=tmp_path)
    assert result.counts["rounds"] == 1
    assert len(result.extras["completed_rounds"]) == 1
    return result, result.extras["completed_rounds"][0]


def test_completed_round_summary_marks_all_bot_takeover_of_human_roster(tmp_path):
    events = _completed_round()
    for event in _play_events(events):
        event["bot"] = True
        event["decision"] = {"policy": "bot-a"}

    result, summary = _summary_for(tmp_path, events)

    assert summary["roster_human_seats"] == [0]
    assert summary["roster_human_bot_activity_seats"] == [0]
    assert summary["human_seats"] == []
    assert summary["bot_seats"] == sorted({event["seat"] for event in events
                                            if event["e"] == "play"})
    assert summary["mixed_controller_seats"] == []
    assert summary["unknown_seats"] == []
    assert summary["bot_policies"] == {str(seat): ["bot-a"] for seat in range(4)}
    assert summary["unknown_policy_count"] == {str(seat): 0 for seat in range(4)}
    assert summary["unknown_policy_total"] == 0
    assert summary["observational_only"] is True
    assert summary["outcome"] == {
        "attacker_points": result.public[0]["outcome"]["attacker_points"],
        "winner_team": result.public[0]["outcome"]["winner_team"],
        "level_change": result.public[0]["outcome"]["level_change"],
    }


def test_completed_round_summary_tracks_mixed_seat_and_policy_drift(tmp_path):
    events = _completed_round()
    plays = _play_events(events)
    for event in plays:
        event["bot"] = True
        event["decision"] = {"policy": "bot-a"}
    plays[0]["bot"] = False
    plays[1]["decision"] = {"policy": "bot-b"}
    plays[2]["decision"] = {}
    plays[3]["decision"] = {"policy": "   "}
    plays[4]["decision"] = {"policy": 7}

    _, summary = _summary_for(tmp_path, events)

    assert summary["mixed_controller_seats"] == [plays[0]["seat"]]
    assert summary["human_seats"] == []
    assert summary["bot_seats"] == sorted({event["seat"] for event in plays
                                            if event["bot"] is True}
                                           - {plays[0]["seat"]})
    mixed_seat = str(plays[0]["seat"])
    assert summary["seat_counts"][mixed_seat] == {
        "human": sum(1 for event in plays
                      if event["seat"] == plays[0]["seat"]
                      and event["bot"] is False),
        "bot": sum(1 for event in plays
                    if event["seat"] == plays[0]["seat"]
                    and event["bot"] is True),
        "unknown": 0,
    }
    assert summary["bot_policies"][str(plays[0]["seat"])] == ["bot-a"]
    assert summary["unknown_policy_total"] == 3
    assert sum(summary["unknown_policy_count"].values()) == 3


@pytest.mark.parametrize("marker", [0, "false", None, _MISSING])
def test_completed_round_summary_treats_nonboolean_markers_as_unknown(tmp_path,
                                                                       marker):
    events = _completed_round()
    plays = _play_events(events)
    for event in plays:
        event["bot"] = False
    play = plays[0]
    if marker is _MISSING:
        play.pop("bot")
    else:
        play["bot"] = marker

    _, summary = _summary_for(tmp_path, events)

    seat = str(play["seat"])
    assert summary["seat_counts"][seat] == {
        "human": sum(1 for event in plays
                      if event["seat"] == play["seat"]
                      and event.get("bot") is False),
        "bot": 0,
        "unknown": 1,
    }
    assert play["seat"] not in summary["human_seats"]
    assert play["seat"] in summary["unknown_seats"]


def test_completed_round_summary_excludes_rejected_and_incomplete_rounds(tmp_path):
    valid = _completed_round()
    incomplete = _completed_round()
    rejected = _completed_round()
    for events, round_no in ((incomplete, 2), (rejected, 3)):
        for event in events:
            event["round"] = round_no
    incomplete.pop()
    rejected[-1]["attacker_points"] += 1
    events = valid + incomplete + rejected

    result, summary = _summary_for(tmp_path, events)

    assert summary["round"] == 1
    assert result.counts["rounds_incomplete"] == 1
    assert result.counts["rounds_rejected"] == 1


def test_completed_round_summary_is_written_to_room_log_sidecar(tmp_path):
    events = _completed_round()
    for event in _play_events(events):
        event["bot"] = True
        event["decision"] = {"policy": "bot-a"}
    source = tmp_path / "logs" / "ROOM.jsonl"
    source.parent.mkdir()
    _write_jsonl(source, events)
    result = extract_room_logs(files=[source], registry=InputRegistry(),
                               repo=tmp_path)

    sidecar = write_source(tmp_path / "out", result, cap=256)
    raw = json.loads((tmp_path / "out" / "room-log.manifest.json").read_text())

    assert raw["extras"]["completed_rounds"] == result.extras["completed_rounds"]
    assert sidecar["extras"]["completed_rounds"][0]["observational_only"] is True

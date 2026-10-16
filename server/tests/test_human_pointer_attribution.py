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
from shengji.harvest.rebuild import engine_level_change, round_from_setup
from shengji.harvest.room_log import extract_round, read_rounds
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

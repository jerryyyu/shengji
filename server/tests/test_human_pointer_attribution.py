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
from shengji.harvest.manifest import build_manifest, write_source
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


@pytest.mark.parametrize("degraded", [None, False, True])
def test_room_log_harvest_preserves_search_degradation(tmp_path, degraded):
    from shengji.harvest.schema import encode_line

    events = _completed_round()
    play = next(event for event in events if event["e"] == "play")
    stats = {}
    if degraded is not None:
        failures = 2 if degraded else 0
        stats = {
            "belief_fallback": 0,
            "world_draws_by_stage": {"base": 1, "lead_confirm": 2, "adaptive_worlds": 0},
            "belief_fallback_by_stage": {"base": 0, "lead_confirm": failures, "adaptive_worlds": 0},
            "belief_fallback_all_draws": failures,
            "belief_fallback_any": int(degraded),
            "history_fill_worlds_by_stage": {"base": 0, "lead_confirm": failures, "adaptive_worlds": 0},
            "history_unchecked_worlds_by_stage": {"base": 0, "lead_confirm": 0, "adaptive_worlds": 0},
            "history_fill_worlds_all_draws": failures,
            "history_unchecked_worlds_all_draws": 0,
            "history_fallback_worlds": 0,
            "leaf_greedy_deadline_fired": False,
            "leaf_greedy_deadline_fired_lead_confirm": bool(degraded),
            "leaf_greedy_deadline_fired_any": bool(degraded),
        }
    play.update(bot=True, decision={"schema": "pv-search-decision-v1", "policy": "synthetic-pv",
                                    "played": list(play["cards"]), **stats})
    source = tmp_path / "room.jsonl"
    _write_jsonl(source, events)
    rounds, bad = read_rounds(source, InputRegistry())
    assert bad == 0
    records, counts = extract_round("logs/room.jsonl", 1, rounds[1], fallback_policy=None)
    assert counts["decision_blobs"] == 1
    record = next(r for r in records if r["decision_kind"] == "play")
    saved = json.loads(encode_line(record))
    assert saved["action"] == play["cards"]
    allocation = saved["allocation"]
    if degraded is None:
        assert "belief_fallback_any" not in allocation
        assert "belief_fallback_by_stage" not in allocation
        assert "leaf_greedy_deadline_fired_any" not in allocation
    else:
        assert {key: allocation[key] for key in stats} == stats
        assert allocation["belief_fallback"] == 0
        assert allocation["belief_fallback_any"] == int(degraded)
        record["allocation"]["belief_fallback_by_stage"]["lead_confirm"] = 999
        original_play = next(event for event in rounds[1] if event["e"] == "play")
        assert original_play["decision"]["belief_fallback_by_stage"]["lead_confirm"] == failures


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
    report = raw["extras"]["human_team_report"]
    assert report["completed_rounds"] == 1
    assert report["eligible_rounds"] == 0
    assert report["excluded_rounds"] == {"all_bot": 1}
    assert report["by_observed_policy"] == {}


@pytest.mark.parametrize("human_team", [0, 1])
def test_full_team_metric_reaches_serialized_manifest(tmp_path, human_team):
    events = _completed_round()
    for event in _play_events(events):
        event["bot"] = event["seat"] % 2 != human_team
        event["decision"] = {"policy": "observed-policy"}
    result, summary = _summary_for(tmp_path, events)
    write_source(tmp_path / "out", result, cap=256)
    raw = json.loads((tmp_path / "out" / "room-log.manifest.json").read_text())
    report = raw["extras"]["human_team_report"]
    bot_win = summary["outcome"]["winner_team"] != human_team
    levels = summary["outcome"]["level_change"] * (1 if bot_win else -1)
    assert report["eligible_rounds"] == report["completed_rounds"] == 1
    assert report["excluded_rounds"] == {}
    assert report["by_observed_policy"] == {"observed-policy": {
        "rounds": 1, "bot_wins": int(bot_win),
        "human_flag_wins": int(not bot_win), "bot_signed_levels": levels,
        "bot_win_rate": float(bot_win), "bot_levels_per_round": float(levels),
    }}
    assert report["observational_only"] is True
    manifest = build_manifest(tmp_path / "out")
    assert manifest["sources"]["room-log"]["extras"]["human_team_report"] == report


@pytest.mark.parametrize("fault,reason", [
    ("takeover", "mixed_controller"),
    ("unknown_controller", "unknown_controller"),
    ("mixed_team", "not_full_opposing_teams"),
    ("policy_drift", "mixed_bot_policy"),
    ("missing_policy", "unknown_bot_policy"),
])
def test_team_metric_excludes_ambiguous_matchups(tmp_path, fault, reason):
    events = _completed_round()
    plays = _play_events(events)
    for event in plays:
        event["bot"] = event["seat"] % 2 == 1
        event["decision"] = {"policy": "observed-policy"}
    human_play = next(event for event in plays if event["seat"] % 2 == 0)
    bot_play = next(event for event in plays if event["seat"] % 2 == 1)
    if fault == "takeover":
        human_play["bot"] = True
    elif fault == "unknown_controller":
        human_play["bot"] = 0
    elif fault == "mixed_team":
        for event in plays:
            event["bot"] = event["seat"] in (2, 3)
    elif fault == "policy_drift":
        bot_play["decision"]["policy"] = "different-policy"
    elif fault == "missing_policy":
        bot_play["decision"] = {}
    result, _ = _summary_for(tmp_path, events)
    report = result.extras["human_team_report"]
    assert report["eligible_rounds"] == 0
    assert report["excluded_rounds"] == {reason: 1}
    assert report["by_observed_policy"] == {}


def test_team_metric_preserves_zero_levels_and_policy_populations():
    from shengji.harvest.room_log import _human_team_report

    def row(policy, winner, levels):
        return {
            "human_seats": [0, 2], "bot_seats": [1, 3],
            "unknown_seats": [], "mixed_controller_seats": [],
            "bot_policies": {"1": [policy], "3": [policy]},
            "unknown_policy_count": {"1": 0, "3": 0},
            "outcome": {"winner_team": winner, "level_change": levels},
        }

    report = _human_team_report([row("a", 1, 0), row("a", 0, 2), row("b", 1, 3)])
    assert report["eligible_rounds"] == 3
    assert report["by_observed_policy"]["a"]["bot_win_rate"] == 0.5
    assert report["by_observed_policy"]["a"]["bot_signed_levels"] == -2
    assert report["by_observed_policy"]["a"]["bot_levels_per_round"] == -1
    assert report["by_observed_policy"]["b"]["bot_levels_per_round"] == 3


@pytest.mark.parametrize("levels,gap,near", [
    (["2", "2"], 0, [False, False]),
    (["J", "Q"], -1, [False, True]),
    (["A", "2"], 12, [True, False]),
    (["K", "A"], -1, [True, True]),
])
def test_game_situation_reaches_replayed_round_manifest(tmp_path, levels, gap, near):
    events = _completed_round()
    events[0]["levels"] = levels
    result, summary = _summary_for(tmp_path, events)
    assert summary["game_situation"] == {
        "status": "observed", "team_levels": levels,
        "team0_minus_team1_rank_steps": gap,
        "team_within_two_ranks_of_ace": near,
        "either_team_within_two_ranks_of_ace": any(near),
    }
    write_source(tmp_path / "out", result, cap=256)
    raw = json.loads((tmp_path / "out" / "room-log.manifest.json").read_text())
    assert raw["extras"]["completed_rounds"][0]["game_situation"] == summary["game_situation"]
    levels[0] = "3"
    assert summary["game_situation"]["team_levels"] != levels


@pytest.mark.parametrize("levels", [None, [], ["Q"], ["2"] * 4, ["2", "BJ"], [2, "A"]])
def test_missing_game_situation_is_unknown_not_midgame(levels):
    from shengji.harvest.room_log import _game_situation
    assert _game_situation({"levels": levels}) == {
        "status": "unknown", "reason": "missing_or_invalid_team_levels"}
    assert _game_situation({})["status"] == "unknown"


@pytest.mark.parametrize("bot_team", [0, 1])
def test_game_situation_report_uses_verified_outcome_and_controller_gate(tmp_path, bot_team):
    events = _completed_round()
    events[0]["levels"] = ["2", "Q"]
    for event in _play_events(events):
        event["bot"] = event["seat"] % 2 == bot_team
        event["decision"] = {"policy": "exact-policy"}
    result, summary = _summary_for(tmp_path, events)
    report = result.extras["game_situation_report"]
    win = summary["outcome"]["winner_team"] == bot_team
    assert report["eligible_rounds"] == 1
    assert report["by_observed_policy"] == {"exact-policy": {"near_ace": {
        "rounds": 1, "bot_wins": int(win),
        "bot_signed_levels": (1 if win else -1) * summary["outcome"]["level_change"],
        "bot_levels_per_round": (1 if win else -1) * summary["outcome"]["level_change"],
    }}}
    write_source(tmp_path / "out", result, cap=256)
    saved = json.loads((tmp_path / "out" / "room-log.manifest.json").read_text())
    assert saved["extras"]["game_situation_report"] == report


def test_game_situation_report_separates_unknown_takeover_and_zero_outcomes():
    from copy import deepcopy
    from shengji.harvest.room_log import _game_situation_report
    row = {"human_seats": [0, 2], "bot_seats": [1, 3],
           "unknown_seats": [], "mixed_controller_seats": [],
           "bot_policies": {"1": ["p"], "3": ["p"]},
           "unknown_policy_count": {"1": 0, "3": 0},
           "outcome": {"winner_team": 1, "level_change": 0},
           "game_situation": {"status": "observed", "either_team_within_two_ranks_of_ace": False}}
    near = deepcopy(row); near["game_situation"]["either_team_within_two_ranks_of_ace"] = True
    near["outcome"]["level_change"] = 2
    unknown = deepcopy(row); unknown["game_situation"] = {"status": "unknown"}
    takeover = deepcopy(near); takeover["mixed_controller_seats"] = [0]
    report = _game_situation_report([row, near, unknown, takeover])
    assert report["completed_rounds"] == 4 and report["eligible_rounds"] == 2
    assert report["excluded_rounds"] == {"mixed_controller": 1, "unknown_game_situation": 1}
    assert report["by_observed_policy"]["p"]["other"]["bot_levels_per_round"] == 0
    assert report["by_observed_policy"]["p"]["near_ace"]["bot_levels_per_round"] == 2

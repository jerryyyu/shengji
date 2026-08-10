from __future__ import annotations

import hashlib
import importlib.util
import json
import random
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay, actual_play_after


SCRIPT = Path(__file__).parents[1] / "scripts" / \
    "s5_point_protection_census.py"
SPEC = importlib.util.spec_from_file_location("s5_point_protection", SCRIPT)
assert SPEC and SPEC.loader
s5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s5)


def _event(round_no: int, kind: str, **fields) -> dict:
    return {"round": round_no, "e": kind, **fields}


def _completed_round(round_no: int = 1) -> list[dict]:
    rnd = Round("4", 0, random.Random(731))
    events = [_event(
        round_no,
        "round_start",
        deck=list(rnd.deck),
        banker=rnd.banker,
        trump_rank=rnd.trump_rank,
        levels=["4"] * 4,
        players=[
            {"seat": 0, "name": "Private Human", "is_bot": False},
            {"seat": 1, "name": "Bot 1", "is_bot": True},
            {"seat": 2, "name": "Bot 2", "is_bot": True},
            {"seat": 3, "name": "Bot 3", "is_bot": True},
        ],
    )]
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    events.append(_event(
        round_no,
        "trump",
        suit=rnd.trump_suit,
        rank=rnd.trump_rank,
        banker=rnd.banker,
        declared=False,
    ))
    policy = HeuristicBot()
    bury = policy.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, bury)
    events.append(_event(
        round_no, "bury", seat=rnd.banker, cards=bury, bot=True))
    while rnd.phase == "play":
        seat = rnd.turn
        cards = policy.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, cards)
        played = actual_play_after(rnd, seat, previous_last)
        events.append(_event(
            round_no, "play", seat=seat, cards=played, bot=True))
    events.append(_event(
        round_no,
        "round_end",
        attacker_points=rnd.attacker_points,
        kitty=list(rnd.buried),
        kitty_points=rnd.kitty_bonus,
        winner_team="private",
    ))
    return events


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(event) + "\n" for event in events))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "private-source"
    source_root.mkdir()
    source = source_root / "PRIVATE-ROOM-NAME.jsonl"
    _write_jsonl(source, _completed_round())
    manifest = tmp_path / "source.sha256"
    manifest.write_text(f"{_digest(source)}  {source.name}\n")
    return manifest, source_root, source


class _Rollout:
    def __init__(self, action: list[str]):
        self.action = action

    def decide_play(self, _rnd, _seat: int) -> list[str]:
        return list(self.action)


class _PolicySurface:
    def __init__(self, candidates: list[list[str]], rollout: list[str]):
        self.candidates = candidates
        self.rollout_policy = _Rollout(rollout)

    def _candidates(self, _rnd, _seat: int) -> list[list[str]]:
        return [list(action) for action in self.candidates]

    def _current_winner(self, rnd) -> tuple[int, str, int]:
        return HeuristicBot()._current_winner(rnd)


def _losing_follow_state() -> Round:
    rnd = Round("2", 0, random.Random(3))
    rnd.trump_suit = "S"
    rnd.trump_is_nt = False
    rnd.ordering = Ordering("S", "2")
    rnd.phase = "play"
    rnd.turn = 1
    rnd.hands = [["C3"], ["H5", "H3"], ["C4"], ["C5"]]
    rnd.trick = Trick(leader=0, plays=[TrickPlay(0, ["HA"])])
    return rnd


def _equal_point_follow_state() -> Round:
    """The cheaper H10 and historical HK both carry exactly 10 points."""
    rnd = Round("2", 0, random.Random(19))
    rnd.trump_suit = "S"
    rnd.trump_is_nt = False
    rnd.ordering = Ordering("S", "2")
    rnd.phase = "play"
    rnd.turn = 1
    rnd.hands = [["C3"], ["H10", "HK"], ["C4"], ["C5"]]
    rnd.trick = Trick(leader=0, plays=[TrickPlay(0, ["HA"])])
    return rnd


def test_distinct_multisets_and_legal_follow_universe_are_exhaustive() -> None:
    actions, examined = s5._multiset_actions(["H3", "H3", "H5"], 2, 10)
    assert set(actions) == {("H3", "H3"), ("H3", "H5")}
    assert examined == 2

    rnd = _losing_follow_state()
    legal, examined = s5.legal_follow_actions(rnd, 1)
    assert legal == [("H3",), ("H5",)]
    assert examined == 2


def test_multiset_enumeration_refuses_above_declared_cap() -> None:
    with pytest.raises(s5.RowRefused, match="cap exceeded"):
        s5._multiset_actions(["C3", "C4", "C5", "C6", "C7"], 2, 2)


def test_trigger_proves_avoidable_points_and_current_incumbent_reproduction() -> None:
    bot = _PolicySurface([["H5"], ["H3"]], ["H3"])
    row = s5.analyze_bot_follow(
        _losing_follow_state(),
        1,
        ["H5"],
        {"bot": True},
        source_sha256="a" * 64,
        round_no=2,
        event_index=7,
        production_bot=bot,
    )
    row = s5._finalize_row(row, final_winner=0, seat=1)
    assert row["structural_trigger"] is True
    assert row["avoidable_point_delta"] == 5
    assert row["legal_winner_count"] == 0
    assert row["lower_point_on_current_ballot"] is True
    assert row["current_candidate0_matches_historical"] is True
    assert row["rollout_policy_matches_historical"] is False
    assert row["reproduced_by_current_policy_surface"] is True
    assert row["classification"] == \
        "historical_identity_unknown_current_ballot_has_lower"
    assert s5.forbidden_public_paths(row) == []


def test_equal_point_only_alternative_is_not_a_protection_trigger(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The S5 defect requires strictly fewer points, not merely another play."""
    bot = _PolicySurface([["HK"], ["H10"]], ["H10"])
    monkeypatch.setattr(s5, "_logged_decision", lambda *_args, **_kwargs: {
        "present": True,
        "valid": True,
        "problems": [],
        "candidates": [
            s5.action_key(["HK"]),
            s5.action_key(["H10"]),
        ],
        "work_complete": True,
    })
    rnd = _equal_point_follow_state()
    assert rnd.ordering is not None
    assert rnd.ordering.level("H10") < rnd.ordering.level("HK")
    row = s5.analyze_bot_follow(
        rnd,
        1,
        ["HK"],
        {"bot": True},
        source_sha256="c" * 64,
        round_no=3,
        event_index=8,
        production_bot=bot,
    )
    row = s5._finalize_row(row, final_winner=0, seat=1)

    assert row["legal_action_count"] == 2
    assert row["historical_points"] == 10
    assert row["minimum_legal_points"] == 10
    assert row["minimum_action_count"] == 2
    assert row["avoidable_point_delta"] == 0
    assert row["lower_point_legal_count"] == 0
    assert row["lower_point_on_current_ballot"] is False
    assert row["lower_point_on_logged_ballot"] is False
    assert row["structural_trigger"] is False
    assert row["classification"] is None


def test_historical_trigger_can_be_distinguished_from_current_surface() -> None:
    bot = _PolicySurface([["H3"], ["H5"]], ["H3"])
    row = s5.analyze_bot_follow(
        _losing_follow_state(),
        1,
        ["H5"],
        {"bot": True},
        source_sha256="b" * 64,
        round_no=1,
        event_index=4,
        production_bot=bot,
    )
    row = s5._finalize_row(row, final_winner=0, seat=1)
    assert row["structural_trigger"] is True
    assert row["reproduced_by_current_policy_surface"] is False


def _valid_logged_decision(bot, candidates: list[list[str]]) -> dict:
    return {
        "schema": "mc-decision-v2",
        "policy": s5.CHAMPION,
        "policy_class": type(bot).__name__,
        "code": {
            "mcbot_sha256": s5.sha256_file(
                s5.SERVER / "shengji/ai/mcbot.py"),
        },
        "ballot": s5.ballot_identity(bot),
        "candidates": candidates,
        "played": candidates[0],
        "played_index": 0,
        "reason": "report_lcb_below_min_gain",
        "work": {"complete": True},
    }


def test_logged_champion_record_requires_exact_ballot_and_replay_binding() -> None:
    bot = s5.make_bot(s5.CHAMPION, seed=0)
    candidates = [["H5"], ["H3"]]
    legal = {s5.action_key(action) for action in candidates}
    event = {"decision": _valid_logged_decision(bot, candidates)}
    result = s5._logged_decision(
        event, ("H5",), legal, bot,
        [s5.action_key(action) for action in candidates])
    assert result["valid"] is True

    drifted = json.loads(json.dumps(event))
    drifted["decision"]["candidates"].reverse()
    result = s5._logged_decision(
        drifted, ("H5",), legal, bot,
        [s5.action_key(action) for action in candidates])
    assert "candidate_replay" in result["problems"]
    assert result["valid"] is False

    drifted = json.loads(json.dumps(event))
    drifted["decision"]["ballot"]["digest"] = "0" * 12
    result = s5._logged_decision(
        drifted, ("H5",), legal, bot,
        [s5.action_key(action) for action in candidates])
    assert "ballot_identity" in result["problems"]


def test_manifest_hash_mismatch_refuses_before_replay(tmp_path: Path) -> None:
    manifest, source_root, _ = _source_fixture(tmp_path)
    with pytest.raises(s5.CensusRefused, match="manifest SHA-256 drift"):
        s5.source_population(
            manifest, source_root, "0" * 64, smoke=True)


def test_source_mutation_during_read_refuses_before_analysis(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, source_root, source = _source_fixture(tmp_path)
    members, _ = s5.source_population(
        manifest, source_root, _digest(manifest), smoke=True)
    original_group = s5.group_rounds

    def mutate_after_read(path: str):
        rounds = original_group(path)
        source.write_bytes(source.read_bytes() + b"\n")
        return rounds

    monkeypatch.setattr(s5, "group_rounds", mutate_after_read)
    with pytest.raises(s5.CensusRefused, match="during replay read"):
        s5.census_sources(
            members, s5.make_bot(s5.CHAMPION, seed=0))


def test_score_free_census_never_calls_mc_and_publishes_no_private_fields(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, source_root, _ = _source_fixture(tmp_path)
    bot_type = type(s5.make_bot(s5.CHAMPION, seed=0))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("score-free census attempted MC work")

    monkeypatch.setattr(bot_type, "decide_play", forbidden)
    monkeypatch.setattr(bot_type, "_sample_hands", forbidden)
    monkeypatch.setattr(bot_type, "_rollout", forbidden)
    packet = s5.build_census(
        manifest,
        source_root,
        _digest(manifest),
        smoke=True,
        runtime_payload={"test_runtime": True},
    )

    assert packet["stats"]["rounds_replayed_complete"] == 1
    assert packet["stats"]["bot_follow_rows_analyzed"] > 0
    assert packet["authority"]["belief_worlds_sampled"] == 0
    assert packet["authority"]["candidate_rollouts"] == 0
    assert s5.forbidden_public_paths(packet) == []
    encoded = json.dumps(packet, sort_keys=True)
    assert "Private Human" not in encoded
    assert "PRIVATE-ROOM-NAME.jsonl" not in encoded
    assert s5.packet_problems(packet, packet) == []


def test_packet_validator_rejects_private_field_and_authority_widening() -> None:
    expected = {
        "authority": {
            "score_free": True,
            "round_scores_read": False,
            "belief_worlds_sampled": 0,
            "candidate_rollouts": 0,
            "full_champion_mc_replays": 0,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
        },
    }
    leaked = json.loads(json.dumps(expected))
    leaked["witness"] = {"cards": ["H5"]}
    assert "private/raw field leaked into census" in \
        s5.packet_problems(leaked, expected)

    widened = json.loads(json.dumps(expected))
    widened["authority"]["training_authorized"] = True
    assert "score-free authority drift" in \
        s5.packet_problems(widened, expected)


def test_exclusive_publication_refuses_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "census.json"
    s5.publish_exclusive(out, {"schema": s5.SCHEMA})
    original = out.read_bytes()
    with pytest.raises(s5.CensusRefused, match="overwrite"):
        s5.publish_exclusive(out, {"schema": "changed"})
    assert out.read_bytes() == original


def test_real_cli_requires_explicit_git_and_packet_pins(tmp_path: Path) -> None:
    base = [
        "freeze",
        "--source-manifest", str(tmp_path / "missing-manifest"),
        "--source-root", str(tmp_path),
        "--expected-source-manifest-sha256", "0" * 64,
        "--out", str(tmp_path / "out.json"),
    ]
    with pytest.raises(s5.CensusRefused, match="requires --expected-git"):
        s5.main(base)

    verify = ["verify", *base[1:], "--expected-git", s5._git(
        "rev-parse", "HEAD")]
    with pytest.raises(
            s5.CensusRefused, match="requires --expected-packet-sha256"):
        s5.main(verify)

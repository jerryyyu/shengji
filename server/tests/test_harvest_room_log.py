"""room-log extractor: counts vs expectations, round-trip, determinism."""
import json
import random

import pytest

from shengji.harvest import legal, rebuild, room_log
from shengji.harvest.common import REPO, InputRegistry
from shengji.harvest.schema import encode_line, validate_record

EXPECTED_ROUNDS = {"main": 164, "archive": 17, "local": 11}   # 192
#: the spec's "~12,700 plays" counts logs/*.jsonl + logs/archive; the 11
#: local rounds add ~800 more (measured: 12,732 + 796 = 13,528)
EXPECTED_PLAYS_MAIN_ARCHIVE = 12_700
EXPECTED_DECISION_BLOBS = 2_257


def _within(actual, expected, tol=0.02):
    return abs(actual - expected) <= tol * expected


@pytest.fixture(scope="module")
def extraction():
    return room_log.extract_room_logs(registry=InputRegistry())


def test_counts(extraction):
    c = extraction.counts
    per_dir = extraction.extras["per_directory"]
    print(f"room-log counts: {c}\nroom-log per directory: {per_dir}")
    assert c["rounds"] == sum(EXPECTED_ROUNDS.values()) == 192
    assert {k: v["rounds"] for k, v in per_dir.items()} == EXPECTED_ROUNDS
    main_archive = per_dir["main"]["plays"] + per_dir["archive"]["plays"]
    assert _within(main_archive, EXPECTED_PLAYS_MAIN_ARCHIVE), main_archive
    assert c["plays"] == main_archive + per_dir["local"]["plays"]
    assert c["decision_blobs"] >= EXPECTED_DECISION_BLOBS, c["decision_blobs"]
    assert c["rounds_rejected"] == 0, extraction.extras["rejections"]
    assert c["bury_records"] == c["rounds"]
    assert len(extraction.public) == c["plays"] + c["bury_records"]
    assert not extraction.private


def _round_end(source_ref):
    name, rno = source_ref.split(":")[0], int(source_ref.split(":round-")[1].split(":")[0])
    path = REPO / name
    for line in open(path):
        e = json.loads(line)
        if e.get("round") == rno and e.get("e") == "round_end":
            return e
    raise AssertionError(source_ref)


def test_round_trip_sample(extraction):
    rng = random.Random(3)
    plays = [r for r in extraction.public if r["decision_kind"] == "play"]
    buries = [r for r in extraction.public if r["decision_kind"] == "bury"]
    sample = rng.sample(plays, 300) + rng.sample(buries, 20)
    for record in sample:
        validate_record(record)
        rnd = rebuild.state_for_record(record)
        assert rnd.turn == record["seat"]
        end = _round_end(record["source_ref"])
        assert record["outcome"]["attacker_points"] == end["attacker_points"]
        assert record["outcome"]["winner_team"] == end["winner_team"]
        assert record["outcome"]["signed_level_utility"] == rebuild.signed_level_utility(
            end["attacker_points"], banker_seat=record["setup"]["banker"],
            perspective_seat=record["seat"])
        if record["decision_kind"] == "play":
            assert rnd.phase == "play"
            assert legal.is_legal(rnd, record["seat"], record["action"])
            assert record["ply"] == len(record["plays_prefix"])
            assert tuple(sorted(record["action"])) in {
                tuple(a) for a in record["legal_actions"]}
            if record["ballot"] is not None:
                for a in record["ballot"]:
                    assert legal.is_legal(rnd, record["seat"], a)
                assert record["allocation"]["n_by_candidate"]
                assert len(record["allocation"]["means"]) == len(record["ballot"])
            rnd.play(record["seat"], record["action"])     # the engine accepts it
        else:
            assert rnd.phase == "bury" and rnd.turn == record["seat"]
            rnd.bury(record["seat"], record["action"])
            assert rnd.phase == "play"


def test_policies_and_ballots(extraction):
    plays = [r for r in extraction.public if r["decision_kind"] == "play"]
    humans = [r for r in plays if r["policy"].startswith("human:")]
    scripts = [r for r in plays if r["policy"].startswith("script:")]
    bots = [r for r in plays if r["policy"] == "mc-s0-report-lcb"]
    assert humans and bots
    # ``human_plays`` counts every ``bot: false`` event; test-script seats
    # (Smoke / X) are labelled script:<id>, never human:<id>
    assert len(humans) + len(scripts) == extraction.counts["human_plays"]
    assert all(r["ballot"] is None and r["allocation"] is None for r in humans)
    assert sum(1 for r in plays if r["ballot"] is not None) == extraction.counts["decision_blobs"]
    assert all(r["deck"] and len(r["deck"]) == 108 for r in plays)
    assert all(r["hidden_hands"] is None for r in plays)


def test_deterministic_rerun(extraction):
    again = room_log.extract_room_logs(registry=InputRegistry())
    assert [encode_line(r) for r in again.public] == [encode_line(r) for r in extraction.public]
    assert again.inputs == extraction.inputs

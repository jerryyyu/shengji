"""Fixture-backed tests for the point-census tooling: manifest binding,
classification, legality filtering, determinism, and no implicit writes."""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts/point_census"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import points  # noqa: E402
from shengji.engine.round import Round  # noqa: E402


def _synthetic_log(path: Path, seed: int = 5) -> None:
    """Write one engine-generated round in the server log format.

    Seat 0 is the human; the other seats are bots."""
    rnd = Round("2", 0, random.Random(seed))
    deck = list(rnd.deck)
    # Mirror replay_log.rebuild_round exactly so the fixture replays
    # byte-for-byte through the same reconstruction path.
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = deck[100:]
    actors = [make_bot("smart") for _ in range(4)]
    events = [{"e": "round_start", "round": 1, "banker": 0, "trump_rank": "2",
               "deck": deck,
               "players": [{"seat": s, "name": f"P{s}"} for s in range(4)]}]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        choice = actors[seat].decide_declare(rnd, seat)
        if choice:
            rnd.declare(seat, choice)
            events.append({"e": "declare", "round": 1, "seat": seat,
                           "cards": list(choice), "bot": seat != 0})
    for seat in range(4):
        choice = actors[seat].decide_declare(rnd, seat, final=True)
        if choice:
            rnd.declare(seat, choice)
            events.append({"e": "declare", "round": 1, "seat": seat,
                           "cards": list(choice), "bot": seat != 0})
    rnd.finalize_declare()
    events.append({"e": "trump", "round": 1, "banker": rnd.banker})
    bury = list(actors[rnd.banker].decide_bury(rnd, rnd.banker))
    rnd.bury(rnd.banker, bury)
    events.append({"e": "bury", "round": 1, "cards": bury})
    while rnd.phase == "play":
        seat = rnd.turn
        cards = actors[seat].decide_play(rnd, seat)
        events.append({"e": "play", "round": 1, "seat": seat,
                       "cards": list(cards), "bot": seat != 0})
        rnd.play(seat, list(cards))
        if rnd.last_trick is not None and (rnd.trick is None
                                           or not rnd.trick.plays):
            trick = rnd.last_trick
            events.append({
                "e": "trick", "round": 1,
                "winner": rnd.last_trick_winner,
                "points": sum(points(c) for tp in trick.plays
                              for c in tp.cards),
                "plays": [{"seat": tp.seat, "cards": list(tp.cards)}
                          for tp in trick.plays]})
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    logs = tmp_path_factory.mktemp("logs")
    _synthetic_log(logs / "FIXT.jsonl")
    manifest = common.build_manifest(str(logs))
    mpath = logs.parent / "manifest.json"
    mpath.write_bytes(common.canonical(manifest))
    return logs, mpath


def test_manifest_roundtrip_and_tamper_refusal(corpus):
    logs, mpath = corpus
    manifest, ordered = common.load_validated_manifest(str(mpath), str(logs))
    assert [p.name for p in ordered] == ["FIXT.jsonl"]
    assert manifest["totals"]["rounds"] == 1
    log = logs / "FIXT.jsonl"
    original = log.read_bytes()
    log.write_bytes(original + b"\n")
    with pytest.raises(SystemExit, match="drift"):
        common.load_validated_manifest(str(mpath), str(logs))
    log.write_bytes(original)


def test_iter_decisions_yields_only_the_human_seat(corpus):
    logs, mpath = corpus
    _, ordered = common.load_validated_manifest(str(mpath), str(logs))
    rows = list(common.iter_decisions(ordered))
    assert rows, "fixture round produced no human decisions"
    assert {seat for _, _, _, _, seat, _ in rows} == {0}


def test_legal_point_filter_and_boss_classification(corpus):
    logs, mpath = corpus
    _, ordered = common.load_validated_manifest(str(mpath), str(logs))
    checked = 0
    for _, _, _, rnd, seat, _ in common.iter_decisions(ordered):
        is_lead, winning, partner, _, to_act = common.trick_context(rnd, seat)
        if is_lead or winning is None:
            continue
        for action in common.legal_point_actions(rnd, seat):
            assert sum(points(c) for c in action) > 0
        cls, literal = common.classify_boss(
            rnd, seat, winning[0], winning[1], winning[2], to_act)
        assert cls in ("literal", "inferred_strict", "inferred_loose",
                       "open", "complex")
        assert literal == (cls == "literal")
        checked += 1
    assert checked > 0


def test_decision_key_is_stable_and_order_free():
    a = common.decision_key("m" * 64, "A.jsonl", 1, 3)
    assert a == common.decision_key("m" * 64, "A.jsonl", 1, 3)
    assert a != common.decision_key("m" * 64, "A.jsonl", 1, 4)


def test_e1_stdout_only_deterministic_no_writes(corpus, tmp_path):
    logs, mpath = corpus
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    outputs = []
    for _ in range(2):
        before = set(os.listdir(tmp_path))
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "e1_census.py"),
             "--logs-dir", str(logs), "--manifest", str(mpath)],
            cwd=tmp_path, env=env, capture_output=True)
        assert completed.returncode == 0, completed.stderr[-400:]
        assert set(os.listdir(tmp_path)) == before, "script wrote files"
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1], "output is not deterministic"
    value = json.loads(outputs[0])
    assert value["schema"] == "point-census-e1-v2"
    assert value["decisions"] > 0

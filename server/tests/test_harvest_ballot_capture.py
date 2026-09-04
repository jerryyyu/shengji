"""Ballot-capture report (issue #205 step 1).

1. every variant is a superset of production at every sampled state;
2. every added candidate is engine-legal;
3. ``production`` captures 100% of the production bot's own contested
   room-log plays (a wrong-seat production set would not);
4. the report is byte-deterministic and the human off-production count
   reproduces the ballot-gap report (158 = lead 115 / follow 43).

States: a handful rebuilt from the harvested human and Luna files plus a
tiny hand-built round.  The harvested files are read only; no hand ever
appears in an assertion message.
"""
import json
import os
import random
from collections import Counter
from pathlib import Path

import pytest

from shengji.engine.cards import make_deck
from shengji.harvest import ballot_capture as bc
from shengji.harvest import cli
from shengji.harvest.common import action_key
from shengji.harvest.legal import clone_for_probe, engine_accepts, is_legal
from shengji.harvest.rebuild import deck_from_seed, round_from_setup, state_for_record

HARVEST_OUT = Path(os.environ.get(
    "SHENGJI_HARVEST_OUT", "/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/harvest-out"))
HUMAN = HARVEST_OUT / "human.jsonl"
LUNA = HARVEST_OUT / "luna-rpc.private.jsonl"
ROOM_LOG = HARVEST_OUT / "room-log.jsonl"
BALLOT_GAP = HARVEST_OUT / "ballot_gap.json"
PRODUCTION_POLICY = "mc-s0-report-lcb"


def _need(*paths: Path) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        pytest.skip(f"harvest output not present: {missing}")


def _play_rows(path: Path, *, every: int = 1, limit: int | None = None,
               pred=None) -> list[dict]:
    """Play records of a harvest file (every ``every``-th line), streamed."""
    out: list[dict] = []
    with path.open() as fh:
        for i, line in enumerate(fh):
            if i % every:
                continue
            record = json.loads(line)
            if record["decision_kind"] != "play":
                continue
            if pred is not None and not pred(record):
                continue
            out.append(record)
            if limit is not None and len(out) >= limit:
                break
    return out


def _hand_built_states() -> list[tuple[str, object]]:
    """A tiny hand-built round: seeded deal, no declaration (the kitty flip
    names trump), banker buries eight cards.  Returns the banker's lead
    state and the next seat's follow state after a single-card lead."""
    deck = deck_from_seed("2", 0, 11)
    setup = {"trump_rank": "2", "banker": 0, "declarations": [],
             "trump_suit": None, "trump_is_nt": False, "buried": None}
    rnd = round_from_setup(deck, setup, stop_before_bury=True, check_trump=False)
    o = rnd.ordering
    hand = sorted(rnd.hands[0], key=o.sort_key)
    rnd.bury(0, hand[:8])
    assert rnd.phase == "play" and rnd.turn == 0
    follow = clone_for_probe(rnd)
    lead_card = max(follow.hands[0], key=o.sort_key)      # a single, always legal
    follow.play(0, [lead_card])
    assert follow.turn == 1 and len(follow.trick.plays) == 1
    return [("hand-built lead", rnd), ("hand-built follow", follow)]


@pytest.fixture(scope="module")
def sampled():
    """``(label, round, seat)`` for a handful of rebuilt states from both
    files plus the hand-built states."""
    _need(HUMAN, LUNA)
    states = []
    for path in (HUMAN, LUNA):
        for record in _play_rows(path, every=97, limit=40):
            rnd = state_for_record(record)
            states.append((f"{record['source']}:{record['ply']}", rnd, record["seat"]))
    for label, rnd in _hand_built_states():
        states.append((label, rnd, rnd.turn))
    assert len(states) >= 60
    return states


# ---------------------------------------------------------------- test 1

def test_every_variant_is_a_superset_of_production(sampled):
    phases = Counter()
    for label, rnd, seat in sampled:
        sets = bc.variant_sets(rnd, seat)
        prod = bc.production_set(rnd, seat)
        assert set(sets) == set(bc.VARIANTS)
        assert sets["production"] == prod and len(prod) >= 1
        for name in bc.VARIANTS:
            dropped = prod - sets[name]
            assert not dropped, f"{label}: variant {name} drops {len(dropped)} " \
                                f"production candidate(s)"
        # the named pure functions agree with the shared computation
        assert bc.wide_set(rnd, seat) == sets["wide"]
        assert bc.all_trump_set(rnd, seat) == sets["all-trump"]
        assert bc.top_suit_set(rnd, seat, 2) == sets["top-2-suit"]
        assert bc.top_suit_set(rnd, seat, 3) == sets["top-3-suit"]
        assert bc.points_set(rnd, seat) == sets["points"]
        assert bc.union_set(rnd, seat) == sets["union"] == (
            sets["wide"] | sets["all-trump"] | sets["top-3-suit"] | sets["points"])
        assert sets["top-2-suit"] <= sets["top-3-suit"]
        if rnd.trick.plays:
            phases["follow"] += 1
            # structural lead variants leave follows unchanged
            assert sets["all-trump"] == prod
            assert sets["top-2-suit"] == prod and sets["top-3-suit"] == prod
        else:
            phases["lead"] += 1
        bc.check_invariants(rnd, seat, sets)
    assert phases["lead"] >= 5 and phases["follow"] >= 5
    # the report-side guard refuses a variant that lost a production candidate
    label, rnd, seat = sampled[0]
    sets = bc.variant_sets(rnd, seat)
    broken = dict(sets)
    broken["all-trump"] = sets["all-trump"] - {sorted(sets["production"])[0]}
    with pytest.raises(bc.BallotCaptureError, match="lacks"):
        bc.check_invariants(rnd, seat, broken)


# ---------------------------------------------------------------- test 2

def test_every_added_candidate_is_engine_legal(sampled):
    added_total = 0
    for label, rnd, seat in sampled:
        sets = bc.variant_sets(rnd, seat)
        for name, keys in sets.items():
            for key in keys:
                assert is_legal(rnd, seat, list(key)), \
                    f"{label}: variant {name} offers an illegal {len(key)}-card action"
        added = set().union(*sets.values()) - sets["production"]
        # brute-force oracle: the engine itself accepts every added action
        for key in sorted(added):
            assert engine_accepts(rnd, seat, list(key)), \
                f"{label}: engine refuses an added {len(key)}-card action"
        added_total += len(added)
    assert added_total > 0
    # the report-side guard refuses an injected illegal single
    label, rnd, seat = next(s for s in sampled if not s[1].trick.plays)
    sets = bc.variant_sets(rnd, seat)
    absent = next(c for c in sorted(set(make_deck())) if c not in rnd.hands[seat])
    broken = dict(sets)
    broken["points"] = sets["points"] | {(absent,)}
    with pytest.raises(bc.BallotCaptureError, match="illegal"):
        bc.check_invariants(rnd, seat, broken)


def test_lead_classification_on_hand_built_state():
    (_, rnd), _ = _hand_built_states()
    seat = rnd.turn
    o = rnd.ordering
    by_suit: dict[str, list[str]] = {}
    for c in rnd.hands[seat]:
        by_suit.setdefault(o.eff_suit(c), []).append(c)
    suit, cards = max(by_suit.items(), key=lambda kv: len({o.level(c) for c in kv[1]}))
    levels = sorted({o.level(c) for c in cards}, reverse=True)
    assert len(levels) >= 4
    by_level = {o.level(c): c for c in cards}
    expect = {0: "highest", 1: "second", len(levels) - 1: "lowest"}
    for i, level in enumerate(levels):
        shape, suit_class, pos = bc.classify_lead(rnd, seat, [by_level[level]])
        assert shape == "single"
        assert suit_class == ("trump" if suit == "T" else "off-suit")
        assert pos == expect.get(i, "middle")
    pair = next((c for c, k in Counter(cards).items() if k >= 2), None)
    if pair is not None:
        assert bc.classify_lead(rnd, seat, [pair, pair])[0] == "pair"


# ---------------------------------------------------------------- test 3

def test_production_captures_its_own_room_log_plays():
    _need(ROOM_LOG)
    rows = _play_rows(ROOM_LOG, pred=lambda r: r["policy"] == PRODUCTION_POLICY)
    assert len(rows) >= 1000
    contested = []
    for record in rows:
        rnd = state_for_record(record)
        seat = record["seat"]
        prod = bc.production_set(rnd, seat)
        if len(prod) > 1:
            contested.append((action_key(record["action"]), prod))
    assert len(contested) >= 200
    sample = random.Random(205).sample(contested, 200)
    captured = sum(1 for key, prod in sample if key in prod)
    print(f"production capture on {PRODUCTION_POLICY} room-log plays: "
          f"{captured}/200 of a sample from {len(contested)} contested")
    assert captured == 200


# ---------------------------------------------------------------- test 4

def test_report_is_deterministic_and_reproduces_ballot_gap(tmp_path):
    _need(HUMAN, LUNA)
    runs = []
    for i in range(2):
        report = bc.build_report(human=HUMAN, luna=LUNA,
                                 variants=("production", "wide"))
        json_path, md_path = bc.write_report(tmp_path / f"run{i}", report)
        runs.append((json_path.read_bytes(), md_path.read_bytes()))
    assert runs[0][0] == runs[1][0], "ballot_capture.json differs between runs"
    assert runs[0][1] == runs[1][1], "ballot_capture.md differs between runs"
    report = json.loads(runs[0][0])
    assert report["schema"] == bc.SCHEMA
    assert report["variant_order"] == ["production", "wide"]
    human = report["sources"]["human"]
    assert human["counts"]["play_decisions"] == 2830
    assert human["counts"]["contested"] == 2316
    prod = human["variants"]["production"]
    assert (prod["overall"]["uncaptured"], prod["lead"]["uncaptured"],
            prod["follow"]["uncaptured"]) == (158, 115, 43)
    assert prod["lead"]["contested"] == 715 and prod["follow"]["contested"] == 1601
    if BALLOT_GAP.is_file():
        gap = json.loads(BALLOT_GAP.read_text())["human"]
        assert gap["overall"]["off_ballot"] == prod["overall"]["uncaptured"]
        assert gap["by_phase"]["lead"]["off_ballot"] == prod["lead"]["uncaptured"]
        assert gap["by_phase"]["follow"]["off_ballot"] == prod["follow"]["uncaptured"]
        assert gap["overall"]["contested"] == human["counts"]["contested"]
    wide = human["variants"]["wide"]
    assert wide["overall"]["uncaptured"] <= prod["overall"]["uncaptured"]
    luna = report["sources"]["luna"]
    assert luna["counts"]["play_decisions"] == 4808
    # no hidden-hand data: the report holds no card lists at all
    assert "hands_by_seat" not in runs[0][0].decode() and "buried" not in runs[0][0].decode()


# ------------------------------------------------------------------- cli

def test_cli_ballot_capture_small(tmp_path):
    _need(HUMAN, LUNA)
    out = tmp_path / "out"
    assert cli.main(["ballot-capture", "--out", str(out), "--inputs", str(HARVEST_OUT),
                     "--limit", "40", "--variants", "points", "wide"]) == 0
    report = json.loads((out / "ballot_capture.json").read_text())
    assert report["variant_order"] == ["production", "wide", "points"]   # canonical
    assert set(report["variants"]) == {"production", "wide", "points"}
    assert set(report["sources"]) == {"human", "luna"}
    assert report["sources"]["human"]["counts"]["rows"] == 40
    md = (out / "ballot_capture.md").read_text()
    assert "| production |" in md and "| wide |" in md
    # a directory without inputs skips both sources with a note, no crash
    empty = tmp_path / "empty"
    assert cli.main(["ballot-capture", "--out", str(empty)]) == 0
    report = json.loads((empty / "ballot_capture.json").read_text())
    assert report["sources"] == {}
    assert sum("source skipped" in n for n in report["notes"]) == 2

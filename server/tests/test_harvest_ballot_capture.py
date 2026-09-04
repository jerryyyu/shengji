"""Ballot-capture report (issue #205 step 1).

1. every variant is a superset of production at every sampled state;
2. every added candidate is engine-legal;
3. ``production`` IS the production bot's ballot: at every rebuilt state it
   equals the ballot the bot enumerated live while the record was generated,
   so it captures every play the bot chose from that ballot and none of the
   exploration-added plays (a wrong-seat production set would do neither);
4. the report is byte-deterministic and every cell equals an independent
   recount of the records;
5. the CLI writes exactly the library's report from a harvest-layout directory.

Fixtures are built inside the session from the engine alone -- no harvest
artifact is read, nothing is committed:

* a reduced-work ``shengji.harvest.trajectory`` run (2 rounds, N=2 selection /
  R=30 report worlds, root exploration on so a few plays land off-production;
  ~6 s of pure-engine self-play).  Every row carries its deck, and rows whose
  ballot exploration widened carry ``production_ballot`` = the plain
  ``MCBot._candidates`` list -- the live production ballot the tool must
  reproduce from the rebuilt state;
* hand-built rows at a seeded deal with classification known by construction
  (single by position, pair, throw, trump single, a point-card follow).

The human_v8 / Luna numbers of the ballot-gap report are an OPTIONAL
local-corpus check at the end: it runs only when ``SHENGJI_HARVEST_OUT``
names the private harvest output and skips everywhere else (CI included).
"""
import json
import os
import random
from collections import Counter
from pathlib import Path

import pytest

from shengji.engine.cards import TRUMP, make_deck, points
from shengji.engine.legal import suit_cards
from shengji.harvest import ballot_capture as bc
from shengji.harvest import cli, trajectory
from shengji.harvest.common import action_key, sha256_file, write_jsonl
from shengji.harvest.legal import clone_for_probe, engine_accepts, is_legal
from shengji.harvest.rebuild import (deck_from_seed, round_from_setup,
                                     setup_from_round, state_for_record)
from shengji.harvest.schema import finalize_record, validate_record
from shengji.luna.game import PRODUCTION_POLICY

SEED0 = 4_205_000                                       # deal-cluster seed
ROUNDS = 2                                              # one cluster, both mirrors
WORK = {"select_worlds": 2, "report_worlds": 30}        # the LCB minimum
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}
HAND_SEED = 11


# ------------------------------------------------------------ synthesized run

def _live_production(record: dict) -> set[bc.Key]:
    """The production ballot the generator's bot enumerated at this state:
    ``production_ballot`` when exploration widened the ballot, else the
    ballot itself (``explore_rate`` 0 reproduces production exactly)."""
    return {action_key(c) for c in record.get("production_ballot", record["ballot"])}


def _explore_played(record: dict) -> bool:
    ex = record.get("exploration")
    return ex is not None and action_key(record["action"]) in {
        action_key(a) for a in ex["added"]}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """``{"path", "records", "counts", "config"}`` of a reduced-work
    trajectory run generated for this session."""
    out = tmp_path_factory.mktemp("trajectory") / "run"
    manifest = trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out,
                                   workers=1, merge=True, **WORK, **EXPLORE)
    path = out / "trajectory.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    counts = manifest["counts"]
    assert counts["rounds"] == ROUNDS and len(records) == counts["records"] >= 100
    assert counts["explore_fired"] > 0 and counts["explore_added"] > 0
    for record in records:
        validate_record(record)
        assert record["source"] == "trajectory" and record["decision_kind"] == "play"
        assert record["hidden_hands"] is None                # nothing private
    return {"path": path, "records": records, "counts": counts,
            "config": manifest["config"]}


# --------------------------------------------------------------- hand-built

def _hand_built_round():
    """Seeded deal, trump rank 2, banker 0, no declaration (the kitty flip
    names trump); the banker buries the eight lowest cards.  Returns
    ``(deck, setup, round)`` with ``setup`` complete for a record."""
    deck = deck_from_seed("2", 0, HAND_SEED)
    rnd = round_from_setup(deck, {"trump_rank": "2", "banker": 0, "declarations": [],
                                  "trump_suit": None, "trump_is_nt": False,
                                  "buried": None},
                           stop_before_bury=True, check_trump=False)
    hand = sorted(rnd.hands[0], key=rnd.ordering.sort_key)
    rnd.bury(0, hand[:8])
    assert rnd.phase == "play" and rnd.turn == 0
    return deck, setup_from_round(rnd), rnd


def _point_follow_lead(rnd) -> str:
    """A single-card lead by the banker after which seat 1 holds at least
    two distinct cards of the led (plain) suit, a point card among them."""
    o = rnd.ordering
    for card in sorted(set(rnd.hands[0]), key=o.sort_key):
        suit = o.eff_suit(card)
        held = suit_cards(rnd.hands[1], suit, o)
        if suit != TRUMP and len(set(held)) >= 2 and any(points(c) for c in held):
            return card
    raise AssertionError("the hand-built deal gives no contested point-card follow")


def _hand_built_states() -> list[tuple[str, object]]:
    """The banker's lead state and seat 1's follow state after the
    single-card lead of ``_point_follow_lead``."""
    _, _, rnd = _hand_built_round()
    follow = clone_for_probe(rnd)
    follow.play(0, [_point_follow_lead(rnd)])
    assert follow.turn == 1 and len(follow.trick.plays) == 1
    return [("hand-built lead", rnd), ("hand-built follow", follow)]


def _position(levels: list[int], level: int) -> str:
    i = levels.index(level)
    return ("highest" if i == 0 else "lowest" if i == len(levels) - 1
            else "second" if i == 1 else "middle")


def _hand_built_rows() -> tuple[list[dict], list[dict]]:
    """Decision records at the hand-built deal and the decision each must
    score as.  Phase and lead category are known by construction; capture is
    membership in the variant sets at the rebuilt state."""
    deck, setup, rnd = _hand_built_round()
    o = rnd.ordering
    hand = rnd.hands[0]
    lead_sets = bc.variant_sets(rnd, 0)
    prod = lead_sets["production"]
    by_suit: dict[str, list[str]] = {}
    for c in hand:
        by_suit.setdefault(o.eff_suit(c), []).append(c)
    # an off-production single of the plain suit with the most distinct levels
    suit, cards = max(((s, cs) for s, cs in by_suit.items() if s != TRUMP),
                      key=lambda kv: len({o.level(c) for c in kv[1]}))
    levels = sorted({o.level(c) for c in cards}, reverse=True)
    assert len(levels) >= 4
    off = next(c for c in sorted(set(cards), key=lambda c: (-o.level(c), c))
               if (c,) not in prod)
    pair = next(c for c, k in sorted(Counter(hand).items()) if k >= 2)
    two = sorted(set(cards))[:2]                     # same suit, distinct codes
    assert len(two) == 2 and abs(o.level(two[0]) - o.level(two[1])) != 1
    trump_top = max(set(suit_cards(hand, TRUMP, o)), key=lambda c: (o.level(c), c))
    trump_levels = sorted({o.level(c) for c in suit_cards(hand, TRUMP, o)}, reverse=True)
    lead_card = _point_follow_lead(rnd)
    follow = clone_for_probe(rnd)
    follow.play(0, [lead_card])
    follow_sets = bc.variant_sets(follow, 1)
    led = o.eff_suit(lead_card)
    point = next(c for c in sorted(set(suit_cards(follow.hands[1], led, o))) if points(c))

    def row(ref, seat, prefix, action):
        return finalize_record({
            "source": "trajectory", "source_ref": f"hand-built:{ref}",
            "policy": "hand-built", "round_seed": HAND_SEED, "deck": deck,
            "setup": setup, "plays_prefix": prefix, "seat": seat,
            "ply": len(prefix), "trick": len(prefix) // 4,
            "role": "banker-team" if seat % 2 == 0 else "attacker-team",
            "action": list(action)})

    def decision(sets, action, phase, category):
        key = action_key(action)
        return {"phase": phase, "contested": len(sets["production"]) > 1,
                "captured": {v: key in sets[v] for v in bc.VARIANTS},
                "sizes": {v: len(sets[v]) for v in bc.VARIANTS},
                "lead_category": category}

    cases = [
        ("off-production-single", 0, [], [off],
         ("single", "off-suit", _position(levels, o.level(off)))),
        ("pair", 0, [], [pair, pair], ("pair", "trump" if o.eff_suit(pair) == TRUMP
                                       else "off-suit", None)),
        ("throw", 0, [], two, ("throw", "off-suit", None)),
        ("trump-single", 0, [], [trump_top],
         ("single", "trump", _position(trump_levels, o.level(trump_top)))),
        ("point-follow", 1, [{"seat": 0, "cards": [lead_card]}], [point], None),
    ]
    rows, expected = [], []
    for ref, seat, prefix, action, category in cases:
        rows.append(row(ref, seat, prefix, action))
        sets = follow_sets if prefix else lead_sets
        expected.append(decision(sets, action, "follow" if prefix else "lead", category))
    # by construction: the single is off-production; the point single is on
    # the points ballot of a single-card follow; follows add nothing else
    assert not expected[0]["captured"]["production"] and expected[0]["contested"]
    assert expected[4]["captured"]["points"]
    assert follow_sets["all-trump"] == follow_sets["top-3-suit"] == follow_sets["production"]
    return rows, expected


@pytest.fixture(scope="module")
def hand_rows(tmp_path_factory):
    rows, expected = _hand_built_rows()
    path = tmp_path_factory.mktemp("hand-built") / "hand-built.jsonl"
    write_jsonl(path, rows)
    return {"path": path, "records": rows, "expected": expected}


@pytest.fixture(scope="module")
def states(run):
    """``(label, round, seat)`` at every synthesized record plus the
    hand-built states."""
    out = [(r["source_ref"], state_for_record(r), r["seat"]) for r in run["records"]]
    out += [(label, rnd, rnd.turn) for label, rnd in _hand_built_states()]
    leads = sum(1 for _, rnd, _ in out if not rnd.trick.plays)
    assert leads >= 20 and len(out) - leads >= 20
    return out


# ---------------------------------------------------------------- test 1

def test_every_variant_is_a_superset_of_production(states):
    phases = Counter()
    for label, rnd, seat in states:
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
    assert phases["lead"] >= 20 and phases["follow"] >= 20
    # the report-side guard refuses a variant that lost a production candidate
    label, rnd, seat = states[0]
    sets = bc.variant_sets(rnd, seat)
    broken = dict(sets)
    broken["all-trump"] = sets["all-trump"] - {sorted(sets["production"])[0]}
    with pytest.raises(bc.BallotCaptureError, match="lacks"):
        bc.check_invariants(rnd, seat, broken)


# ---------------------------------------------------------------- test 2

def test_every_added_candidate_is_engine_legal(states):
    added_total = 0
    for label, rnd, seat in states:
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
    label, rnd, seat = next(s for s in states if not s[1].trick.plays)
    sets = bc.variant_sets(rnd, seat)
    absent = next(c for c in sorted(set(make_deck())) if c not in rnd.hands[seat])
    broken = dict(sets)
    broken["points"] = sets["points"] | {(absent,)}
    with pytest.raises(bc.BallotCaptureError, match="illegal"):
        bc.check_invariants(rnd, seat, broken)


# ---------------------------------------------------------------- test 3

def test_production_set_is_the_live_production_ballot(run):
    """The tool's production set at the rebuilt state equals the ballot the
    production bot enumerated live, record by record; capture is exactly
    "the bot chose from its own ballot" (exploration-added plays are the
    only uncaptured ones)."""
    assert run["config"]["policy"] == trajectory.DEFAULT_POLICY == PRODUCTION_POLICY
    contested = captured = uncaptured = 0
    for record in run["records"]:
        rnd = state_for_record(record)
        seat = record["seat"]
        assert rnd.phase == "play" and rnd.turn == seat
        live = _live_production(record)
        prod = bc.production_set(rnd, seat)
        assert prod == live, f"{record['source_ref']}: production set differs " \
                             f"from the live ballot (+{len(prod - live)} -{len(live - prod)})"
        key = action_key(record["action"])
        if _explore_played(record):
            assert key not in prod, f"{record['source_ref']}: exploration play captured"
        else:
            assert key in prod, f"{record['source_ref']}: production play not captured"
        if len(prod) > 1:
            contested += 1
            captured += key in prod
            uncaptured += key not in prod
    assert contested >= 50 and captured >= 50
    assert uncaptured == sum(1 for r in run["records"]
                             if _explore_played(r) and len(_live_production(r)) > 1)
    # the scorer refuses a row whose seat is not on turn at the rebuilt state
    record = run["records"][0]
    with pytest.raises(bc.BallotCaptureError, match="not the seat's play turn"):
        bc.score_record({**record, "seat": (record["seat"] + 1) % 4}, ("wide",))


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
        assert suit_class == ("trump" if suit == TRUMP else "off-suit")
        assert pos == expect.get(i, "middle")
    pair = next((c for c, k in Counter(cards).items() if k >= 2), None)
    if pair is not None:
        assert bc.classify_lead(rnd, seat, [pair, pair])[0] == "pair"


def test_hand_built_rows_score_as_designed(hand_rows):
    for record, expected in zip(hand_rows["records"], hand_rows["expected"]):
        assert bc.score_record(record, bc.VARIANTS) == expected, record["source_ref"]
    # ...and the only variants that ever change a follow are wide/points/union
    follow = bc.score_record(hand_rows["records"][-1], bc.VARIANTS)
    assert follow["phase"] == "follow" and follow["lead_category"] is None
    assert follow["captured"]["points"] and follow["sizes"]["all-trump"] == \
        follow["sizes"]["top-2-suit"] == follow["sizes"]["production"]


# ---------------------------------------------------------------- test 4

def _recount(decisions: list[dict], names: list[str]) -> dict:
    """The per-variant cells of one source, the long way (no ``aggregate``)."""
    out = {}
    for v in names:
        cells = {}
        for scope in ("overall", "lead", "follow"):
            ds = [d for d in decisions if scope == "overall" or d["phase"] == scope]
            con = [d for d in ds if d["contested"]]
            cap = sum(1 for d in con if d["captured"][v])
            sizes = [d["sizes"][v] for d in con]
            cells[scope] = {
                "decisions": len(ds), "contested": len(con), "captured": cap,
                "uncaptured": len(con) - cap, "candidates_max": max(sizes, default=0),
                "capture_rate": cap / len(con) if con else None,
                "candidates_mean": sum(sizes) / len(con) if con else None}
        missed = [d["lead_category"] for d in decisions
                  if d["contested"] and d["phase"] == "lead" and not d["captured"][v]]
        shape_suit = Counter(f"{s}/{c}" for s, c, _ in missed)
        position = Counter(p for _, _, p in missed if p is not None)
        cells["uncaptured_leads"] = {
            "by_shape_suit": {f"{s}/{c}": shape_suit[f"{s}/{c}"]
                              for s in bc.SHAPES for c in bc.SUIT_CLASSES},
            "single_position": {p: position[p] for p in bc.POSITIONS}}
        out[v] = cells
    return out


def test_report_is_deterministic_and_matches_a_recount(run, hand_rows, tmp_path):
    # the report's source slots are named after the harvest files they
    # normally hold; here "human" carries the synthesized run and "luna" the
    # hand-built rows
    runs = []
    for i in range(2):
        report = bc.build_report(human=run["path"], luna=hand_rows["path"])
        json_path, md_path = bc.write_report(tmp_path / f"run{i}", report)
        runs.append((json_path.read_bytes(), md_path.read_bytes()))
    assert runs[0][0] == runs[1][0], "ballot_capture.json differs between runs"
    assert runs[0][1] == runs[1][1], "ballot_capture.md differs between runs"
    text = runs[0][0].decode()
    report = json.loads(text)
    assert report["schema"] == bc.SCHEMA
    assert report["variant_order"] == list(bc.VARIANTS)
    assert set(report["sources"]) == {"human", "luna"}
    # no hidden-hand data and no clock: the report holds counts and rates
    assert "hands_by_seat" not in text and "buried" not in text
    assert not any(k in text for k in ("wall_secs", "started", "timestamp"))
    assert report["inputs"] == [
        {"path": str(p), "sha256": sha256_file(p)}
        for p in sorted((run["path"], hand_rows["path"]), key=str)]
    # the synthesized run: per-record scores against the live ballots, cells
    # against a recount
    decisions = []
    for record in run["records"]:
        d = bc.score_record(record, bc.VARIANTS)
        live = _live_production(record)
        assert d["phase"] == ("lead" if record["ply"] % 4 == 0 else "follow")
        assert d["contested"] == (len(live) > 1)
        assert d["sizes"]["production"] == len(live)
        assert d["captured"]["production"] == (action_key(record["action"]) in live)
        decisions.append(d)
    src = report["sources"]["human"]
    n_contested = sum(1 for d in decisions if d["contested"])
    assert src["counts"] == {
        "rows": len(run["records"]), "play_decisions": len(run["records"]),
        "bury_rows_skipped": 0,
        "engine_play_differs": sum(1 for r in run["records"] if "engine_play" in r),
        "contested": n_contested,
        "contested_lead": sum(1 for d in decisions if d["contested"] and d["phase"] == "lead"),
        "contested_follow": sum(1 for d in decisions if d["contested"] and d["phase"] == "follow")}
    assert n_contested >= 50
    assert src["variants"] == _recount(decisions, report["variant_order"])
    prod = src["variants"]["production"]
    assert prod["overall"]["uncaptured"] == sum(
        1 for r in run["records"] if _explore_played(r) and len(_live_production(r)) > 1)
    for v in bc.VARIANTS:
        cell = src["variants"][v]["overall"]
        assert cell["uncaptured"] <= prod["overall"]["uncaptured"]
        assert cell["candidates_mean"] >= prod["overall"]["candidates_mean"]
    assert src["variants"]["union"]["overall"]["candidates_mean"] >= \
        src["variants"]["wide"]["overall"]["candidates_mean"]
    # the hand-built rows: cells known by construction
    hand = report["sources"]["luna"]
    expected = hand_rows["expected"]
    assert hand["counts"]["play_decisions"] == len(expected) == 5
    assert hand["variants"] == _recount(expected, report["variant_order"])
    prod = hand["variants"]["production"]
    assert prod["lead"]["decisions"] == 4 and prod["follow"]["decisions"] == 1
    assert prod["lead"]["uncaptured"] >= 1
    single = expected[0]["lead_category"]
    assert prod["uncaptured_leads"]["by_shape_suit"]["single/off-suit"] >= 1
    assert prod["uncaptured_leads"]["single_position"][single[2]] >= 1
    assert sum(prod["uncaptured_leads"]["by_shape_suit"].values()) == prod["lead"]["uncaptured"]
    # the markdown carries every variant row of both sources
    lines = runs[0][1].decode().splitlines()
    for v in bc.VARIANTS:
        rows = sum(1 for line in lines if line.startswith(f"| {v} |"))
        assert rows == 6, f"{v}: {rows} table rows, expected 3 tables x 2 sources"
    md = "\n".join(lines)
    assert f"## human: {len(run['records'])} play decisions" in md
    assert "## luna: 5 play decisions" in md
    assert "## Inputs" in md and sha256_file(run["path"]) in md
    # a request without production still reports it first, in canonical order
    partial = bc.build_report(human=run["path"], luna=None, variants=("points", "wide"))
    assert partial["variant_order"] == ["production", "wide", "points"]
    assert set(partial["sources"]) == {"human"}
    assert partial["sources"]["human"]["variants"]["production"] == report["sources"]["human"]["variants"]["production"]
    with pytest.raises(bc.BallotCaptureError, match="unknown variants"):
        bc.build_report(human=run["path"], luna=None, variants=("wide", "narrow"))


# ------------------------------------------------------------------- cli

def test_cli_ballot_capture_writes_the_library_report(run, hand_rows, tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name, src in zip(("human", "luna"), (run["path"], hand_rows["path"])):
        (inputs / dict(bc.SOURCE_FILES)[name]).write_bytes(src.read_bytes())
    out = tmp_path / "out"
    assert cli.main(["ballot-capture", "--out", str(out), "--inputs", str(inputs),
                     "--limit", "40", "--variants", "points", "wide"]) == 0
    report = json.loads((out / "ballot_capture.json").read_text())
    assert report["variant_order"] == ["production", "wide", "points"]   # canonical
    assert set(report["variants"]) == {"production", "wide", "points"}
    assert set(report["sources"]) == {"human", "luna"}
    assert report["sources"]["human"]["counts"]["rows"] == 40
    assert report["sources"]["luna"]["counts"]["rows"] == 5
    assert any(n.startswith("limit: only the first 40 rows") for n in report["notes"])
    md = (out / "ballot_capture.md").read_text()
    assert "| production |" in md and "| wide |" in md and "| points |" in md
    # byte-for-byte the library call with the same arguments
    expected = bc.build_report(human=inputs / "human.jsonl",
                               luna=inputs / "luna-rpc.private.jsonl",
                               variants=("points", "wide"), limit=40)
    json_path, md_path = bc.write_report(tmp_path / "lib", expected)
    assert (out / "ballot_capture.json").read_bytes() == json_path.read_bytes()
    assert (out / "ballot_capture.md").read_bytes() == md_path.read_bytes()
    # --inputs defaults to --out (the ``harvest all`` layout)
    assert cli.main(["ballot-capture", "--out", str(inputs), "--limit", "10"]) == 0
    report = json.loads((inputs / "ballot_capture.json").read_text())
    assert report["variant_order"] == list(bc.VARIANTS)
    assert report["sources"]["human"]["counts"]["rows"] == 10
    # a directory without inputs skips both sources with a note, no crash
    empty = tmp_path / "empty"
    assert cli.main(["ballot-capture", "--out", str(empty)]) == 0
    report = json.loads((empty / "ballot_capture.json").read_text())
    assert report["sources"] == {}
    assert sum("source skipped" in n for n in report["notes"]) == 2


# ------------------------------------------------ optional: local corpus

LOCAL_CORPUS = os.environ.get("SHENGJI_HARVEST_OUT")


def _local(*names: str) -> list[Path]:
    """Files of the developer-local harvest output (``harvest all``), or
    skip.  NOT part of the clean-checkout witness above: these checks
    reproduce the human_v8 / Luna numbers of the ballot-gap report when the
    private corpus is present and skip everywhere else, CI included."""
    if not LOCAL_CORPUS:
        pytest.skip("optional local-corpus check: SHENGJI_HARVEST_OUT unset")
    paths = [Path(LOCAL_CORPUS) / name for name in names]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        pytest.skip(f"optional local-corpus check: not present {missing}")
    return paths


def _play_rows(path: Path, *, pred=None) -> list[dict]:
    out = []
    with path.open() as fh:
        for line in fh:
            record = json.loads(line)
            if record["decision_kind"] == "play" and (pred is None or pred(record)):
                out.append(record)
    return out


def test_local_corpus_reproduces_the_ballot_gap_report(tmp_path):
    human, luna = _local("human.jsonl", "luna-rpc.private.jsonl")
    report = bc.build_report(human=human, luna=luna, variants=("production", "wide"))
    json_path, _ = bc.write_report(tmp_path, report)
    text = json_path.read_text()
    assert "hands_by_seat" not in text and "buried" not in text
    src = report["sources"]["human"]
    assert src["counts"]["play_decisions"] == 2830
    assert src["counts"]["contested"] == 2316
    prod = src["variants"]["production"]
    assert (prod["overall"]["uncaptured"], prod["lead"]["uncaptured"],
            prod["follow"]["uncaptured"]) == (158, 115, 43)
    assert prod["lead"]["contested"] == 715 and prod["follow"]["contested"] == 1601
    assert src["variants"]["wide"]["overall"]["uncaptured"] <= 158
    assert report["sources"]["luna"]["counts"]["play_decisions"] == 4808
    gap_path = Path(LOCAL_CORPUS) / "ballot_gap.json"
    if gap_path.is_file():
        gap = json.loads(gap_path.read_text())["human"]
        assert gap["overall"]["off_ballot"] == prod["overall"]["uncaptured"]
        assert gap["by_phase"]["lead"]["off_ballot"] == prod["lead"]["uncaptured"]
        assert gap["by_phase"]["follow"]["off_ballot"] == prod["follow"]["uncaptured"]
        assert gap["overall"]["contested"] == src["counts"]["contested"]


def test_local_corpus_production_captures_its_own_room_log_plays():
    (room_log,) = _local("room-log.jsonl")
    rows = _play_rows(room_log, pred=lambda r: r["policy"] == PRODUCTION_POLICY)
    assert len(rows) >= 1000
    contested = []
    for record in rows:
        rnd = state_for_record(record)
        prod = bc.production_set(rnd, record["seat"])
        if len(prod) > 1:
            contested.append((action_key(record["action"]), prod))
    assert len(contested) >= 200
    sample = random.Random(205).sample(contested, 200)
    assert sum(1 for key, prod in sample if key in prod) == 200

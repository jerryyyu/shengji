"""luna-rpc extractor: 62 games / 4,808 afterstates, private split, replay."""
import json
import os
import random
from pathlib import Path

import pytest

from shengji.harvest import legal, luna_rpc, rebuild
from shengji.harvest.common import LUNA_ROOTS, InputRegistry
from shengji.harvest.manifest import write_source
from shengji.harvest.schema import encode_line, validate_record

EXPECTED_GAMES = 62
EXPECTED_DECISIONS = 4_808


def _within(actual, expected, tol=0.02):
    return abs(actual - expected) <= tol * expected


@pytest.fixture(scope="module")
def extraction():
    if not all(Path(r).is_dir() for r in LUNA_ROOTS):
        pytest.skip("Luna roots not present")
    return luna_rpc.extract_luna(registry=InputRegistry())


def test_counts(extraction):
    c = extraction.counts
    print(f"luna-rpc counts: {c}")
    assert c["games"] == EXPECTED_GAMES
    assert _within(c["decisions"], EXPECTED_DECISIONS), c["decisions"]
    assert c["decisions"] == len(extraction.public) == len(extraction.private)
    assert c["failed_throws"] == 0


def _terminal(source_ref):
    attempt = Path.home() / ".shengji-runs" / source_ref.split("/trajectory.json")[0]
    return json.loads((attempt / "terminal.json").read_text())


def test_round_trip_private_records(extraction):
    rng = random.Random(9)
    for private in rng.sample(extraction.private, 250):
        validate_record(private)
        assert private["deck"] and private["hidden_hands"]
        rnd = rebuild.state_for_record(private)
        assert rnd.phase == "play" and rnd.turn == private["seat"]
        assert rebuild.hands_snapshot(rnd) == private["hidden_hands"]
        assert legal.is_legal(rnd, private["seat"], private["action"])
        for a in private["ballot"]:
            assert legal.is_legal(rnd, private["seat"], a)
        terminal = _terminal(private["source_ref"])
        assert private["outcome"]["attacker_points"] == terminal["final_attacker_points"]
        assert rebuild.signed_level_utility(
            terminal["final_attacker_points"], banker_seat=private["setup"]["banker"],
            perspective_seat=0) == terminal["signed_level_utility"]
        assert private["outcome"]["signed_level_utility"] == rebuild.signed_level_utility(
            terminal["final_attacker_points"], banker_seat=private["setup"]["banker"],
            perspective_seat=private["seat"])
        rnd.play(private["seat"], private["action"])


def test_public_rows_withhold_state(extraction):
    for public, private in zip(extraction.public, extraction.private):
        assert public["deck"] is None and public["round_seed"] is None
        assert public["state_private"] is True and public["hidden_hands"] is None
        assert private["public_record_sha256"] == public["record_sha256"]
        assert public["ballot"] == private["ballot"]
        assert public["production_ballot"] == private["production_ballot"]
    forced = [r for r in extraction.public if r["policy"] == luna_rpc.FORCED_POLICY]
    assert forced and all(len(r["ballot"]) == 1 for r in forced)
    assert all(len(r["ballot"]) > 1 for r in extraction.public
               if r["policy"] == luna_rpc.POLICY)


def test_private_file_mode_and_determinism(extraction, tmp_path):
    sidecar = write_source(tmp_path, extraction, cap=256)
    private = tmp_path / "luna-rpc.private.jsonl"
    assert (private.stat().st_mode & 0o777) == 0o600
    assert sidecar["outputs"]["luna-rpc.private.jsonl"]["records"] == len(extraction.private)
    again = luna_rpc.extract_luna(registry=InputRegistry())
    assert [encode_line(r) for r in again.private] == [encode_line(r) for r in extraction.private]
    assert [encode_line(r) for r in again.public] == [encode_line(r) for r in extraction.public]
    assert os.path.getsize(private) > 0

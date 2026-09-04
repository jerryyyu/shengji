"""highn extractor: dedupe by (seed, ply), rebuild, ballot/allocation."""
import json
import random

import pytest

from shengji.harvest import highn, legal, rebuild
from shengji.harvest.common import HIGHN_FILES, InputRegistry
from shengji.harvest.schema import encode_line, validate_record

LIMIT = 500


@pytest.fixture(scope="module")
def extraction():
    return highn.extract_highn(registry=InputRegistry(), limit=LIMIT)


def test_dedupe_matches_independent_count():
    keys = set()
    rows = 0
    for path in HIGHN_FILES:
        with open(path) as fh:
            for line in fh:
                row = json.loads(line)
                keys.add((row["seed"], row["ply"]))
                rows += 1
    counted = highn.extract_highn(registry=InputRegistry(), limit=0)
    print(f"highn rows={rows} unique(seed,ply)={len(keys)}")
    assert counted.counts["rows"] == rows
    assert counted.counts["rows"] - counted.counts["duplicates"] == len(keys)
    assert counted.counts["conflicting_duplicates"] == 0


def test_round_trip(extraction):
    assert len(extraction.public) == LIMIT
    for record in random.Random(1).sample(extraction.public, 120):
        validate_record(record)
        rnd = rebuild.state_for_record(record)
        assert rnd.phase == "play" and rnd.turn == record["seat"]
        assert record["round_seed"] is not None
        assert rebuild.deck_from_seed(record["setup"]["trump_rank"], None,
                                      record["round_seed"]) == record["deck"]
        best = record["allocation"]["best"]
        assert record["action"] == record["ballot"][best]
        assert legal.is_legal(rnd, record["seat"], record["action"])
        for a in record["ballot"]:
            assert legal.is_legal(rnd, record["seat"], a)
        assert record["outcome"] is None and record["hidden_hands"] is None
        assert record["policy"] == "mc-highn-240"
        assert len(record["allocation"]["means"]) == len(record["ballot"])
        rnd.play(record["seat"], record["action"])


def test_deterministic(extraction):
    again = highn.extract_highn(registry=InputRegistry(), limit=LIMIT)
    assert [encode_line(r) for r in again.public] == [encode_line(r) for r in extraction.public]


def test_conflicting_duplicate_refuses(tmp_path, monkeypatch):
    """Two rows for one (seed, ply) with different content fail closed."""
    with open(HIGHN_FILES[0]) as fh:
        row = json.loads(fh.readline())
    twin = dict(row)
    twin["conflict_marker"] = 1
    path = tmp_path / "conflict.jsonl"
    path.write_text(json.dumps(row) + "\n" + json.dumps(twin) + "\n")
    monkeypatch.setattr(highn, "_ref", lambda p, repo: "tmp/conflict.jsonl")
    with pytest.raises(highn.HighNFormatError, match="conflicting duplicate"):
        highn.extract_highn(files=[path], registry=InputRegistry())
    # the same file without the conflict extracts (the refusal is specific)
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    ok = highn.extract_highn(files=[path], registry=InputRegistry())
    assert ok.counts["duplicates"] == 1 and ok.counts["conflicting_duplicates"] == 0

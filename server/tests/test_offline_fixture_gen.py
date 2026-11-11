"""The offline-engine fixtures are current, deterministic and complete.

``web/src/offline/fixtures`` holds what ``scripts/gen_offline_engine_fixtures.py``
records from this engine; the TypeScript port is tested against it in vitest.
Regenerating here and comparing byte for byte catches an engine or bot change
that leaves the committed fixtures stale, and under ``SHENGJI_FAST=1`` also
holds the compiled engine to the same recorded verdicts.
"""

import gzip
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gen_offline_engine_fixtures as gen  # noqa: E402

from shengji.engine.cards import Ordering, make_deck  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / "web" / "src" / "offline" / "fixtures"


def _committed(name):
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8")


def test_committed_rounds_regenerate_identically():
    text = _committed("rounds.jsonl.gz")
    header = json.loads(text.split("\n", 1)[0])
    assert header["format"] == gen.FORMAT
    assert gen.rounds_text(header["rounds"], header["seed"]) == text


def test_committed_primitives_regenerate_identically():
    assert gen.primitives_text() == _committed("primitives.json.gz")


def test_committed_fixtures_exercise_every_rule_area():
    header = json.loads(_committed("rounds.jsonl.gz").split("\n", 1)[0])
    stats = header["stats"]
    assert header["rounds"] >= 200
    for key in ("plays", "tricks", "illegal_attempts", "failed_throws",
                "enumerated_decisions", "declare_checks", "declares", "games"):
        assert stats[key] > 0, key
    rounds = [json.loads(line) for line in
              _committed("rounds.jsonl.gz").splitlines()[1:]]
    results = [r["result"] for r in rounds]
    assert any(r["pointScored"] for r in results)
    assert any(r["gameOver"] for r in results)
    assert any(r["kittyPoints"] for r in results)
    assert any(r["trump"]["nt"] for r in rounds)
    assert any(not any(e[2] == "declare" for e in r["declareEvents"])
               for r in rounds), "no round flipped trump from the kitty"
    probe_errors = {o["err"] for r in rounds for _, _, o in r["probes"] if "err" in o}
    for msg in ("You must follow suit.", "You don't hold those cards.",
                "A lead must be a single suit (throws included).",
                "You must play all your cards of the led suit."):
        assert msg in probe_errors, msg
    assert sorted(f.name for f in FIXTURES.iterdir()) == [
        "primitives.json.gz", "rounds.jsonl.gz"]
    assert sum(f.stat().st_size for f in FIXTURES.iterdir()) < 5_000_000


def test_generation_is_deterministic():
    assert gen.rounds_text(3, 7) == gen.rounds_text(3, 7)


def test_enumeration_counts_match_enumerations():
    rng = random.Random(3)
    deck = make_deck()
    for i in range(200):
        o = Ordering(("S", "H", None)[i % 3], "7")
        hand = rng.sample(deck, rng.randint(1, 14))
        n = rng.randint(1, len(hand))
        subs = gen.submultisets(hand, n)
        assert len(subs) == gen.count_submultisets(hand, n)
        assert len({tuple(s) for s in subs}) == len(subs)
        leads = gen.lead_candidates(hand, o)
        assert len(leads) == gen.count_lead_candidates(hand, o)
        assert all(len({o.eff_suit(c) for c in p}) == 1 for p in leads)

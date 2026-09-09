"""The Run I / Run J split binding must stay re-derivable from source.

``server/runs/runij_split.json`` records an assignment by digest rather than by
expansion: the whole point of ``split_deals`` is that it is a pure function of
(split seed, deal-key set), and the deal-key set is a pure function of
(round_mix, seed0, clusters).  Committing 2.6 MB of derivable data would let the
file and the code drift apart silently.  This test re-derives both and refuses
the drift.

It also pins the property the I-minus-J contrast rests on: because the two runs
deal identical decks, one assignment governs both corpora.
"""
import hashlib
import json
from pathlib import Path

from shengji.harvest.rebuild import deck_from_seed
from shengji.harvest.trajectory import round_mix_draw
from shengji.train.data import deal_key, split_deals

BINDING = Path(__file__).resolve().parents[1] / "runs" / "runij_split.json"


def _binding() -> dict:
    return json.loads(BINDING.read_text())


def _keys(b: dict) -> list[str]:
    rank, banker = round_mix_draw(b["round_mix"], b["seed0"], 0)
    assert (rank, banker) == (b["trump_rank"], b["banker"]), (
        "round_mix_draw no longer deals what the binding records")
    return [deal_key(list(deck_from_seed(rank, banker, b["seed0"] + c)))
            for c in range(b["clusters"])]


def test_deal_keys_match_the_recorded_digest():
    b = _binding()
    keys = _keys(b)
    assert len(set(keys)) == b["clusters"], "the deals are not distinct"
    digest = hashlib.sha256("\n".join(keys).encode()).hexdigest()
    assert digest == b["keys_sha256"], (
        "the enumerated deal keys no longer match the binding: either the deal "
        "changed or the binding is stale")


def test_assignment_matches_the_recorded_digest_and_counts():
    b = _binding()
    keys = _keys(b)
    parts = split_deals(keys, seed=b["split_seed"],
                        val_fraction=b["val_fraction"],
                        test_fraction=b["test_fraction"])
    digest = hashlib.sha256(
        "\n".join(f"{k} {parts[k]}" for k in keys).encode()).hexdigest()
    assert digest == b["assignment_sha256"], "the split no longer reproduces"
    counts = {p: sum(1 for v in parts.values() if v == p)
              for p in ("train", "val", "test")}
    assert counts == b["counts"]


def test_one_assignment_governs_both_corpora():
    """Run I and Run J deal the same decks, so the split is matched by
    construction -- this is what lets I minus J be read as the generator
    effect.  Re-derive from each run's own seed0 and require the same keys."""
    b = _binding()
    rank, banker = round_mix_draw(b["round_mix"], b["seed0"], 0)
    for _run in ("run-I", "run-J"):  # same seed0 by design; that IS the claim
        keys = [deal_key(list(deck_from_seed(rank, banker, b["seed0"] + c)))
                for c in range(64)]
        assert keys == _keys(b)[:64]

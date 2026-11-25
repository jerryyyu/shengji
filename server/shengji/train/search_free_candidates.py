"""Convert a resolved candidate shard into pre-play features for search-free training.

Run from server with python -m shengji.train.search_free_candidates SOURCE DEST.
Use the original shard filename under a fresh candidate directory for the trainer.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from ..engine.cards import points
from ..rl.encode import CARD_INDEX
from .belief_history import TOKEN_FLOAT


def load_public_candidates(source: Path) -> tuple[dict[str, np.ndarray], int]:
    """Load one trainer shard and describe every candidate as proposed, before adjudication."""
    with np.load(source, allow_pickle=False) as shard:
        data = {key: shard[key] for key in shard.files}
    floats, cards, attempts = (data[key] for key in ("tok_f", "tok_cards", "tok_att"))
    n = len(data["row"])
    if (floats.shape != (n, len(TOKEN_FLOAT)) or cards.shape != (n, len(CARD_INDEX))
            or attempts.shape != cards.shape or data["tok_int"].shape != (n, 4)
            or any(data[key].shape != (n,) for key in ("mean", "played", "slot"))):
        raise ValueError("inconsistent candidate shard dimensions")
    failed_col = TOKEN_FLOAT.index("failed_throw")
    flag = floats[:, failed_col]
    failed = flag == 1
    if (not np.all((flag == 0) | failed) or not np.array_equal(attempts.any(axis=1), failed)
            or np.any(data["tok_int"][failed, 1] != 0)):
        raise ValueError("inconsistent refused lead")
    proposed = attempts[failed]
    forced = cards[failed]
    if (np.any(proposed > 2) or np.any(forced > proposed) or np.any(forced.sum(axis=1) == 0)
            or np.any(forced.sum(axis=1) >= proposed.sum(axis=1))):
        raise ValueError("forced component must be a proper subset of the throw")

    # A throw and its forced component share one effective suit. Only the length,
    # card points, multiset and refusal fields distinguish their lead tokens.
    card_points = np.zeros(len(CARD_INDEX), dtype=np.float32)
    for code, index in CARD_INDEX.items():
        card_points[index] = points(code)
    floats[failed, TOKEN_FLOAT.index("n_cards")] = proposed.sum(axis=1) / 8.0
    floats[failed, TOKEN_FLOAT.index("play_points")] = proposed @ card_points / 25.0
    floats[failed, failed_col] = 0
    cards[failed] = proposed
    attempts[failed] = 0

    return data, int(failed.sum())


def convert(source: Path, destination: Path) -> int:
    """Publish one compatible NPZ on a filesystem supporting hard links."""
    data, corrected = load_public_candidates(source)
    with NamedTemporaryFile(dir=destination.parent) as tmp:
        np.savez(tmp, **data)
        tmp.flush()
        os.link(tmp.name, destination)
    return corrected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(f"Converted {convert(args.source, args.destination)} refused candidate leads")

#!/usr/bin/env python3
"""Value/prior training pipeline v0 (engine + torch; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_v0.py train \
        --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR \
        [--device mps|cpu] [--epochs 20] [--seed 1] [--prior-target softmax|final] \
        [--limit-clusters N] [--prior-weight 1.0] [--val-fraction 0.1] \
        [--test-fraction 0.1] [--resident-bytes B] \
        [--privacy-witness-every 1 [--allow-sampled-privacy-witness]]
    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_v0.py evaluate \
        --checkpoint CKPT (--data DIR | --eval-luna PATH) --out DIR [--split test]

Rebuilds every decision state with ``shengji.harvest.rebuild``, encodes it
with the production ``shengji.rl.encode`` (the PRIVACY witness runs on
EVERY cached row and refuses an encoder that reads another seat's hand),
caches the encodings per shard, binds every row to its canonical DEAL key
(a digest of the dealt deck, shared by every store / policy / mirror of the
deal), splits three ways by deal (train / val = epoch selection and the
calibration fit, tuning only / test = the reported held-out metrics),
refuses a Luna set that shares a deal with the data stores, trains the v0
trunk + value/prior heads and reports the TEST metrics against the
stratified prior (value) and the uniform / incumbent priors, with
deal-bootstrap CIs, calibration and the Luna evaluation set.  Decoded shard
blocks live in an LRU bounded by ``--resident-bytes`` (default 40% of
physical memory).  See ``shengji/train/`` for the contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.train_v0 import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

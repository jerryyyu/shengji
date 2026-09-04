#!/usr/bin/env python3
"""Value/prior training pipeline v0 (engine + torch; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_v0.py train \
        --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR \
        [--device mps|cpu] [--epochs 20] [--seed 1] [--prior-target softmax|final] \
        [--limit-clusters N] [--prior-weight 1.0]
    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_v0.py evaluate \
        --checkpoint CKPT (--data DIR | --eval-luna PATH) --out DIR

Rebuilds every decision state with ``shengji.harvest.rebuild``, encodes it
with the production ``shengji.rl.encode`` (the PRIVACY witness refuses an
encoder that reads another seat's hand), caches the encodings per shard,
splits by deal cluster, trains the v0 trunk + value/prior heads and reports
held-out metrics against the stratified prior (value) and the uniform /
incumbent priors, with cluster-bootstrap CIs, calibration and the Luna
evaluation set.  See ``shengji/train/`` for the contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.train_v0 import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Complete-world value net: train / evaluate (engine + torch; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_cwv.py train \
        --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR --arch mlp|seq \
        [--device mps|cpu] [--limit-clusters N] [--aux-points] [--seed N] \
        [--public-head CKPT] [--epochs 20] [--batch-size 1024] ...
    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_cwv.py evaluate \
        --checkpoint CKPT (--data DIR | --eval-luna PATH) --out DIR [--public-head CKPT]

Every record's complete round is rebuilt with ``shengji.harvest.rebuild``
(the record carries the deck), its engine-accepted action applied, and the
reached state encoded by ``shengji.rl.value_afterstate.tensors_from_round``
-- the world tensor SEES all four hands and the burial by design (the
play-time consumer feeds sampled worlds).  Rows are cached per shard, split
three ways by deal key (train / val = selection, tuning only / test = the
reported held-out metrics), the Luna private rows are an external held-out
set, and the checkpoint loads through ``shengji.rl.value_checkpoint`` /
``value_inference`` unchanged (the contract with the search consumer).
Reported: expected signed level MAE/MSE vs the stratified prior AND vs the
public head on the same rows (paired, deal-bootstrap CIs), candidate-ranking
agreement with the search's per-candidate means (net / public head / prior),
a calibration table, and positions/second of batched inference on CPU.
See ``shengji/train/cwv_data.py`` for the contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.train_cwv import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

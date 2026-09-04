#!/usr/bin/env python3
"""Sweep ``train_v0`` over a grid of config overrides (engine + torch; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/train_sweep.py \
        --data DIR [--data DIR ...] [--eval-luna PATH] --grid GRID.json --out DIR \
        [--device mps|cpu] [--base BASE.json] [--set KEY=JSON ...] [--cache-workers N]

``GRID.json`` is a list of override objects (``train_v0`` keyword
arguments), e.g. ``[{}, {"aux_search_mean": 1.0}, {"prior_target": "final"},
{"hidden": 128, "weight_decay": 1e-3}]``.  The encoding cache is built once
under ``<out>/cache`` and shared by every run; ``<out>/sweep.json`` and
``<out>/sweep.md`` carry one row per config (config hash, epochs, best
epoch, held-out value MAE/MSE against the stratified prior with the paired
CI, prior CE vs uniform and incumbent, aux search-mean MAE, Luna metrics,
wall time).  A failed config is recorded, not fatal.  See
``shengji/train/sweep.py`` for the contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.sweep import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

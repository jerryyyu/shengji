#!/usr/bin/env python3
"""Natural-trajectory self-play generator (engine only; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/trajectory.py \
        --rounds N --seed S --workers W --out DIR [--policy NAME] \
        [--explore-rate R] [--explore-k K] [--select-worlds n] \
        [--report-worlds n] [--cap 256]

Plays rounds/2 seeded deal clusters in both mirrors with all four seats on
the same registry policy (default mc-s0-report-lcb), captures every play
decision's ballot, allocation and action values from ``MCBot``'s decision
record, fills the final round outcome, and writes ``trajectory.jsonl`` +
``manifest.json`` to DIR.  Fixed seeds reproduce the JSONL byte for byte at
any worker count.  See ``shengji/harvest/trajectory.py`` for the record
mapping, the allocation definition and root exploration.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.harvest.trajectory import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

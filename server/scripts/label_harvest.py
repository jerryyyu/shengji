#!/usr/bin/env python3
"""Label harvested decision records with production's own search (engine
only; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/label_harvest.py \
        --in-dir HARVEST_DIR --out LABEL_DIR [--sources human luna-rpc pt1 room-log highn] \
        [--workers W] [--limit N] [--scale 1|3] [--allow-code-drift] [--no-merge]

Every record's complete round is rebuilt (``shengji.harvest.rebuild``) and
verified against the record (hidden hands, role, the legal set), then the
registry policy ``mc-s0-report-lcb`` (N30/R300; ``--scale 3`` = N90/R900)
runs from the acting seat at a seed derived from ``record_sha256``, with
the PLAYED action force-included on its ballot.  One output row per input
record: the record untouched plus ``search_labels`` (ballot, per-candidate
means in the units of trajectory ``action_values.means``, paired SEs, the
search's choice, the reason, the report fold and allocation, code identity,
wall) or ``label_refusal`` (reason).  Per-(source, worker) shards, resume
by ``record_sha256`` (rerun the same command), merged per-source files
``<source>.labels[.private].jsonl`` and ``manifest.json``.  See
``shengji/train/harvest_labels.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.harvest_labels import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Harvest decision records from every existing pool into one schema.

    python scripts/harvest.py <source> --out DIR    (luna-rpc room-log pt1 highn human)
    python scripts/harvest.py all --out DIR
    python scripts/harvest.py ballot-gap --out DIR
    python scripts/harvest.py manifest DIR

Outputs per source: ``<source>.jsonl`` (public fields) and, for sources with
hidden hands, ``<source>.private.jsonl`` (mode 0600); plus ``manifest.json``
and ``ballot_gap.json``.  See ``shengji/harvest/schema.py`` for the record.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.harvest.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

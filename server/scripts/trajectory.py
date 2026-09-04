#!/usr/bin/env python3
"""Natural-trajectory self-play generator (engine only; no LLM tokens).

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/trajectory.py \
        --rounds N --seed S --workers W --out DIR [--policy NAME] \
        [--explore-rate R] [--explore-k K] [--select-worlds n] \
        [--report-worlds n] [--cap 256] [--knob NAME=VALUE ...] \
        [--widen VARIANT ...] [--merge] [--resume]

Plays rounds/2 seeded deal clusters in both mirrors with all four seats on
the same registry policy (default mc-s0-report-lcb), captures every play
decision's ballot, search-work allocation, preregistered preference target
and action values from ``MCBot``'s decision record, fills the final round
outcome, and publishes each cluster as an immutable shard as soon as it
finishes: ``DIR/shards/cluster-<index:06d>.jsonl`` + ``.json`` sidecar
(sha256, record count, counts), then ``DIR/manifest.json`` (deterministic:
shards in cluster order with their hashes) and ``DIR/runtime.json`` (wall
clock, peak RSS).  ``--merge`` also writes ``DIR/trajectory.jsonl``;
``--resume`` reopens DIR for the same run_id, keeps the shards that verify
and regenerates the rest.  Fixed seeds reproduce every shard byte for byte
at any worker count and across an interruption.

``--knob NAME=VALUE`` (repeatable) overrides a public scalar class attribute
of the policy's class for the DATA policy (e.g. ``V3_LEAD_SINGLES=1
LEAD_MAX_CANDIDATES=64``); ``--widen VARIANT`` (repeatable) appends a
``ballot_capture`` candidate-set variant (``wide``, ``all-trump``,
``top-2-suit``, ``top-3-suit``, ``points``, ``union``) to every search
ballot.  Either way each record's ``production_ballot`` is the UNMODIFIED
production list, ``ballot`` is what the search ran, and the overrides /
variants are part of the run_id and of ``run.json`` / ``manifest.json``
(``config.knobs`` / ``config.widen``), so such a store can never be resumed
or mixed with a plain one.  See ``shengji/harvest/trajectory.py`` for the
record mapping, the allocation and preference definitions, root
exploration, knobs, widening and the shard/resume contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.harvest.trajectory import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

"""Data harvest: one decision-record schema over every existing decision pool.

Design rule (ledger 29871a60 / 7a799e1c): keep RAW, re-encode on demand.
Every record stores engine-reconstructible state (an explicit deck or a round
seed, plus the move prefix), the exhaustive legal set, the producing search's
ballot/allocation, the action taken and the realized outcome. Nothing here is
a tensor; encoding is a separate, versioned step that binds an encoder
identity to a manifest.

Modules
-------
schema      the ``shengji-decision-record-v1`` record, canonical hashing
legal       exhaustive legal-action enumerator (+ brute-force oracle)
rebuild     Round reconstruction from a record (deck/seed + prefix)
common      file hashing, JSONL writers, pseudonyms, extraction results
luna_rpc    ~/.shengji-runs/pt-luna-rpc-*-private trajectories
room_log    logs/*.jsonl (+archive/local) via ``replay_log.rebuild_round``
pt1         shengji-pt1-evidence groups (state via round_seed)
highn       server/rl_data/highn_*.jsonl (+ repo-root copy), deduped
human       server/rl_data/human_v8 pointers resolved through room_log
ballot_gap  teacher actions outside the production ballot (report)
ballot_capture  capture rate of candidate-generator variants on human and
            Luna decisions (report; issue #205 step 1)
manifest    per-extraction manifest (counts + sha256 of inputs/outputs)
cli         ``scripts/harvest.py`` entry point
trajectory  natural-trajectory self-play generator (``scripts/trajectory.py``):
            production search on mirrored seeded deals, root exploration,
            allocation = the search's own world counts, outcome = final result
"""

from .schema import SCHEMA, record_sha256  # noqa: F401

__all__ = ["SCHEMA", "record_sha256"]

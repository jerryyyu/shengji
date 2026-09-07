"""Freeze real trajectory positions and origin/main's v1 observation bytes.

``tests/test_encode_versions.py`` asserts that ``encode_obs(..., version=1)``
still returns exactly what ``origin/main``'s ``encode_obs`` returned, element
for element, on positions drawn from real trajectory shards.  The reference
vectors have to come from code the encoder-v2 change never touched, so this
script materialises ``origin/main:server/shengji/rl/encode.py`` out of git,
executes it as a sibling module (its relative imports resolve against the
current, unmodified engine), and stores the vectors it produces next to the
minimal records they were rebuilt from.

    python -m scripts.build_encoder_v1_fixture <shard-dir>... [--count 240]

The fixture is provenance-stamped with the origin/main commit and the sha256
of the reference ``encode.py``; regenerating it is a deliberate act.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shengji.harvest.rebuild import RebuildError, state_for_record  # noqa: E402

FIXTURE = SERVER / "tests" / "data" / "encoder_v1_positions.json.gz"
REFERENCE = "origin/main"
#: the fields ``state_for_record`` reads; nothing else is kept
KEEP = ("decision_kind", "seat", "setup", "plays_prefix", "round_seed", "deck")


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(SERVER.parent), *args],
                          capture_output=True, text=True, check=True).stdout


def load_reference_encoder():
    """``origin/main``'s ``encode.py`` as a live module (never imported)."""
    source = _git("show", f"{REFERENCE}:server/shengji/rl/encode.py")
    # Placed beside the real encode.py so its ``parents[1] / "ai" / "memory.py"``
    # digest and its relative imports resolve exactly as they do on main.
    path = SERVER / "shengji" / "rl" / "_encode_reference_tmp.py"
    path.write_text(source)
    try:
        module = types.ModuleType("shengji.rl._encode_reference_tmp")
        module.__package__ = "shengji.rl"
        module.__file__ = str(path)
        exec(compile(source, str(path), "exec"), module.__dict__)
    finally:
        path.unlink()
    return module, source


def iter_records(shard_dirs: list[Path]):
    """Round-robin over the runs so the fixture is not one run's shard."""
    per_dir = [sorted(Path(d).glob("*.jsonl")) for d in shard_dirs]
    for rank in range(max((len(files) for files in per_dir), default=0)):
        for shard_dir, files in zip(shard_dirs, per_dir):
            if rank >= len(files):
                continue
            path = files[rank]
            label = f"{Path(shard_dir).parent.name}/{path.name}"
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield label, json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--count", type=int, default=240)
    parser.add_argument("--stride", type=int, default=37)
    args = parser.parse_args()

    reference, source = load_reference_encoder()
    assert reference.OBS_DIM == 531, reference.OBS_DIM
    assert reference.ENC_VERSION == 1

    kept: list[dict] = []
    vectors: list[list[float]] = []
    seen = 0
    for name, record in iter_records([Path(p) for p in args.shards]):
        if record.get("decision_kind") != "play":
            continue
        seen += 1
        if seen % args.stride:
            continue
        try:
            rnd = state_for_record(record)
        except (RebuildError, ValueError, KeyError, AssertionError, TypeError):
            continue
        seat = int(record["seat"])
        if rnd.phase != "play" or rnd.turn != seat:
            continue
        vectors.append(reference.encode_obs(rnd, seat))
        kept.append({"shard": name,
                     "source_ref": record.get("source_ref"),
                     **{k: record[k] for k in KEEP if k in record}})
        if len(kept) >= args.count:
            break

    if len(kept) < 200:
        raise SystemExit(f"only {len(kept)} positions; need at least 200")

    payload = {
        "schema": "encoder-v1-golden-positions-v1",
        "reference": REFERENCE,
        "reference_commit": _git("rev-parse", REFERENCE).strip(),
        "reference_encode_sha256": __import__("hashlib").sha256(
            source.encode()).hexdigest(),
        "obs_dim": int(reference.OBS_DIM),
        "enc_version": int(reference.ENC_VERSION),
        "obs_schema": reference.OBS_SCHEMA,
        "records": kept,
        # exact float32 bytes, base16 per row (the encoder emits Python
        # floats; float32 is the width every consumer stores)
        "obs": [np.asarray(v, dtype=np.float32).tobytes().hex() for v in vectors],
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURE, "wt") as fh:
        json.dump(payload, fh)
    print(f"{len(kept)} positions -> {FIXTURE} "
          f"({FIXTURE.stat().st_size / 1024:.0f} KiB) @ {payload['reference_commit'][:12]}")


if __name__ == "__main__":
    main()

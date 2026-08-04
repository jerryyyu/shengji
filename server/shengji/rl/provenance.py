"""Carry a checkpoint's ballot identity from training to play.

`BallotSpec` gives a ballot a name that cannot drift. That is only half a
contract: the identity has to travel with the weights, or play time has
nothing to compare against and the gate degrades to a warning nobody reads —
which is how v10res and v13abs were lost.

Checkpoints here are bare `state_dict()` files with no metadata envelope, and
several loaders (torch, exported npz, the no-torch production path) read them
directly. So provenance is a sidecar next to the weights rather than a new
container format: nothing needs to re-serialise, and an old loader keeps
working while the gate still sees the record.

    ckpt_v13abs.pt
    ckpt_v13abs.pt.ballot.json      <- written by the trainer
"""
from __future__ import annotations

import json
import os

from ..engine.ballot import (ESCAPE_HATCH, BallotMismatch, BallotSpec,
                             assert_compatible)


def sidecar_path(ckpt_path: str) -> str:
    return f"{ckpt_path}.ballot.json"


def record_ballot(ckpt_path: str, spec: BallotSpec, **extra) -> str:
    """Stamp a checkpoint with the ballot its labels were generated under."""
    path = sidecar_path(ckpt_path)
    payload = {
        "name": spec.name,
        "version": spec.version,
        "source": spec.source,
        "config": [list(kv) for kv in spec.config],
        "source_digest": spec.source_digest,
        "digest": spec.digest,
        "note": spec.note,
        **extra,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp, path)          # atomic: never a half-written identity
    return path


def ballot_of(ckpt_path: str) -> BallotSpec | None:
    """The ballot a checkpoint was trained against, or None if unstamped."""
    path = sidecar_path(ckpt_path)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        d = json.load(fh)
    spec = BallotSpec(
        name=d["name"], version=d["version"], source=d["source"],
        config=tuple(tuple(kv) for kv in d.get("config", ())),
        source_digest=d.get("source_digest", ""), note=d.get("note", ""))
    if spec.digest != d.get("digest"):
        raise BallotMismatch(
            f"{path}: recorded digest {d.get('digest')} does not match the "
            f"identity its own fields produce ({spec.digest}). The sidecar was "
            f"edited or written by an incompatible version; do not trust it.")
    return spec


def require_ballot(ckpt_path: str, played: BallotSpec, *, context: str = "") -> None:
    """Fail closed unless this checkpoint is known to match the play ballot.

    An unstamped checkpoint is a failure, not a pass. Treating "no record" as
    "probably fine" is precisely the default that let three runs be scored
    against action sets they were never trained on.
    """
    labelled = ballot_of(ckpt_path)
    if labelled is None:
        msg = (f"{ckpt_path} carries no ballot provenance, so there is no "
               f"evidence it was trained on the ballot it is about to score "
               f"({played}). Stamp it with rl.provenance.record_ballot(), or "
               f"set {ESCAPE_HATCH}=1 to proceed RESEARCH-ONLY.")
        if os.environ.get(ESCAPE_HATCH):
            print(f"\n*** UNSTAMPED CHECKPOINT ALLOWED BY {ESCAPE_HATCH} ***\n"
                  f"{msg}\n*** Not usable for a strength claim. ***\n",
                  flush=True)
            return
        raise BallotMismatch(msg)
    assert_compatible(labelled, played, context=context or ckpt_path)

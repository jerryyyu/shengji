"""Export an admitted CWV MLP checkpoint to a Torch-free NumPy package."""
from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

from shengji.ai.cwv_numpy import PACKAGE_SCHEMA


def export_cwv_numpy(checkpoint: str | Path, output: str | Path, *,
                     value_head: str | None = None) -> str:
    # Importing the admission path lazily keeps the serving runtime Torch-free.
    from shengji.ai.cwv_policy import load_cwv_checkpoint
    model, metadata, original_sha = load_cwv_checkpoint(checkpoint)
    config = model.config
    if config.architecture != "mlp":
        raise ValueError("only architecture=mlp can be exported")
    # #373: a package carries ONE head.  Default: the checkpoint's own
    # value_head; an override must name a head the net has.
    head = config.value_head if value_head is None else value_head
    if head not in ("outcome", "search-mean"):
        raise ValueError("value_head must be 'outcome' or 'search-mean'")
    if head == "search-mean" and not config.search_head:
        raise ValueError("this checkpoint has no search-mean head to export")
    head_key = "head" if head == "outcome" else "search_head"
    # Training population/exposure manifests can be megabytes of receipts.
    # W32 never reads them. Preserve their identity and the original checkpoint
    # instead of copying the full provenance graph on each room snapshot.
    metadata = dict(metadata)
    for key in ("population", "exposure"):
        manifest = metadata.pop(key, None)
        if manifest is None:
            continue
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        metadata[f"training_{key}_reference"] = {
            "checkpoint_sha256": original_sha,
            "metadata_key": key,
            "canonical_json_sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_json_bytes": len(raw),
        }
    names = {
        "trunk.0.weight": "trunk0_weight", "trunk.0.bias": "trunk0_bias",
        "trunk.3.weight": "trunk1_weight", "trunk.3.bias": "trunk1_bias",
        f"{head_key}.weight": "head_weight", f"{head_key}.bias": "head_bias"}
    metadata["exported_value_head"] = head
    state = model.state_dict()
    weights = {dst: state[src].detach().cpu().numpy().astype(np.float32, copy=True)
               for src, dst in names.items()}
    payload = {"schema": PACKAGE_SCHEMA,
               "config": {"architecture": config.architecture, "width": config.width,
                          "feedforward_width": config.feedforward_width,
                          "public_dim": config.public_dim, "enc_version": config.enc_version},
               "original_checkpoint_sha256": original_sha,
               "metadata": metadata}
    target = Path(output)
    if target.suffix.lower() != ".npz":
        raise ValueError("output must have a .npz suffix")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing export: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".tmp-", suffix=".npz",
                                     dir=str(target.parent))
    try:
        os.close(fd)
        np.savez_compressed(temporary, metadata=np.asarray(json.dumps(payload, sort_keys=True)), **weights)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and fails if another process won the
        # target race; unlike replace(), it never overwrites user data.
        os.link(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    else:
        os.unlink(temporary)
    return original_sha


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: export_cwv_numpy.py CHECKPOINT OUTPUT.npz [outcome|search-mean]")
    print(export_cwv_numpy(sys.argv[1], sys.argv[2],
                           value_head=(sys.argv[3] if len(sys.argv) > 3 else None)))

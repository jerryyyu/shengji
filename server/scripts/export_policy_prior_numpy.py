"""Export a policy_prior checkpoint (#419) to a Torch-free NumPy package (#435)."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

from shengji.ai.cwv_prior_numpy import PRIOR_PACKAGE_SCHEMA, SOURCE_SCHEMA


def export_policy_prior_numpy(checkpoint: str | Path, output: str | Path) -> str:
    from shengji.train.policy_prior import load_prior          # Torch, exporter only
    net, payload = load_prior(checkpoint)
    if payload.get("schema") != SOURCE_SCHEMA:
        raise ValueError("not a policy-prior checkpoint")
    state = {k: v.detach().cpu().numpy().astype(np.float32, copy=True) for k, v in net.state_dict().items()}
    linears = [k[:-len(".weight")] for k in state if k.endswith(".weight")]
    if len(linears) != 3:
        raise ValueError(f"expected three linear layers, found {linears}")
    # Shapes come from the state dict, never from payload['hidden'] (which the trainer hard-codes).
    w = [state[f"{k}.weight"] for k in linears]; b = [state[f"{k}.bias"] for k in linears]
    input_dim, h0, h1 = int(w[0].shape[1]), int(w[0].shape[0]), int(w[1].shape[0])
    if w[1].shape != (h1, h0) or w[2].shape != (54, h1):
        raise ValueError("prior state dict layout drift")
    mu = np.asarray(payload["mu"], dtype=np.float32).reshape(-1); sd = np.asarray(payload["sd"], dtype=np.float32).reshape(-1)
    if mu.shape != (input_dim,) or sd.shape != (input_dim,):
        raise ValueError("mu/sd width drift")
    with open(checkpoint, "rb") as fh:
        original_sha = hashlib.file_digest(fh, "sha256").hexdigest()
    meta = {"schema": PRIOR_PACKAGE_SCHEMA, "source_schema": SOURCE_SCHEMA, "input_dim": input_dim,
            "hidden": [h0, h1], "enc_version": int(payload.get("enc_version", 2)),
            "original_checkpoint_sha256": original_sha,
            "metadata": {k: payload[k] for k in ("epochs", "listwise_weight", "train_rows", "data_sha256") if k in payload}}
    target = Path(output)
    if target.suffix.lower() != ".npz":
        raise ValueError("output must have a .npz suffix")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing export: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".tmp-", suffix=".npz", dir=str(target.parent))
    try:
        os.close(fd)
        np.savez_compressed(temporary, metadata=np.asarray(json.dumps(meta, sort_keys=True)),
                            w0=w[0], b0=b[0], w1=w[1], b1=b[1], w2=w[2], b2=b[2], mu=mu, sd=sd)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        os.link(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise
    else:
        os.unlink(temporary)
    return original_sha


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: export_policy_prior_numpy.py PRIOR.pt OUTPUT.npz")
    print(export_policy_prior_numpy(sys.argv[1], sys.argv[2]))

"""Export an admitted CWV MLP checkpoint to a Torch-free NumPy package."""
from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

from shengji.ai.cwv_numpy import PACKAGE_SCHEMA, PACKAGE_SCHEMA_V2


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
    names = {f"{head_key}.weight": "head_weight", f"{head_key}.bias": "head_bias"}
    cfg = {"architecture": config.architecture, "width": config.width,
           "feedforward_width": config.feedforward_width,
           "public_dim": config.public_dim, "enc_version": config.enc_version}
    if config.trunk_block == "plain" and config.trunk_layers == 2:
        # The deployed schema, byte for byte: every plain model exports as before.
        schema = PACKAGE_SCHEMA
        names.update({"trunk.0.weight": "trunk0_weight", "trunk.0.bias": "trunk0_bias",
                      "trunk.3.weight": "trunk1_weight", "trunk.3.bias": "trunk1_bias"})
    elif config.trunk_block == "residual":
        # value_model: Sequential(Linear stem, *ResidualTrunkBlock x L, LayerNorm, ReLU)
        # -> indices 0 (stem), 1..L (blocks), L+1 (final LayerNorm).
        schema = PACKAGE_SCHEMA_V2
        cfg.update({"trunk_block": "residual", "trunk_layers": config.trunk_layers})
        names.update({"trunk.0.weight": "stem_weight", "trunk.0.bias": "stem_bias"})
        for i in range(config.trunk_layers):
            for part in ("norm", "up", "down"):
                names.update({f"trunk.{i + 1}.{part}.weight": f"block{i}_{part}_weight",
                              f"trunk.{i + 1}.{part}.bias": f"block{i}_{part}_bias"})
        final = config.trunk_layers + 1
        names.update({f"trunk.{final}.weight": "final_norm_weight", f"trunk.{final}.bias": "final_norm_bias"})
    elif config.trunk_block == "grid":
        # value_model.GridTrunk: col_embed, two window reads, row/cell projections, stem,
        # then blocks = Sequential(*ResidualTrunkBlock x L, LayerNorm, ReLU). The per-trump
        # index table (card_grid.grid_table) rides in the package so the served gather
        # is the exported layout, not whatever the runtime's engine says today.
        schema = PACKAGE_SCHEMA_V2
        cfg.update({"trunk_block": "grid", "trunk_layers": config.trunk_layers,
                    "grid_channels": config.grid_channels})
        names.update({"trunk.col_embed": "col_embed",
                      "trunk.win1_w": "win1_weight", "trunk.win1_b": "win1_bias",
                      "trunk.win2_w": "win2_weight", "trunk.win2_b": "win2_bias",
                      "trunk.row_proj.weight": "row_proj_weight", "trunk.row_proj.bias": "row_proj_bias",
                      "trunk.cell_proj.weight": "cell_proj_weight", "trunk.cell_proj.bias": "cell_proj_bias",
                      "trunk.stem.weight": "stem_weight", "trunk.stem.bias": "stem_bias"})
        for i in range(config.trunk_layers):
            for part in ("norm", "up", "down"):
                names.update({f"trunk.blocks.{i}.{part}.weight": f"block{i}_{part}_weight",
                              f"trunk.blocks.{i}.{part}.bias": f"block{i}_{part}_bias"})
        final = config.trunk_layers
        names.update({f"trunk.blocks.{final}.weight": "final_norm_weight",
                      f"trunk.blocks.{final}.bias": "final_norm_bias"})
    else:
        raise ValueError(f"trunk {config.trunk_block!r} x {config.trunk_layers} has no numpy runtime")
    if config.policy_head:
        # #425 joint net: the policy head rides in the SAME package (v2 schema), so
        # one file serves the value net and, via `cwv_prior_admission`, the prior.
        if schema == PACKAGE_SCHEMA:
            schema = PACKAGE_SCHEMA_V2
            cfg.update({"trunk_block": config.trunk_block, "trunk_layers": config.trunk_layers})
        cfg["policy_head"] = True
        names.update({"policy_head.weight": "policy_weight", "policy_head.bias": "policy_bias"})
    metadata["exported_value_head"] = head
    state = model.state_dict()
    missing = [src for src in names if src not in state]
    if missing:
        raise ValueError(f"checkpoint state lacks {missing[:3]}: layout drift")
    weights = {dst: state[src].detach().cpu().numpy().astype(np.float32, copy=True)
               for src, dst in names.items()}
    if config.trunk_block == "grid":
        from shengji.rl.card_grid import grid_table
        table = grid_table()
        if not np.array_equal(table, model.trunk.table.detach().cpu().numpy()):
            raise ValueError("the checkpoint's grid table differs from card_grid.grid_table(): layout drift")
        weights["grid_table"] = table.astype(np.float32)
    payload = {"schema": schema, "config": cfg,
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

"""Grow the residual stacks of a warm RT4 checkpoint before changing its width."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile

import torch
from shengji.train import unified_readout as ur


def deepen(source, digest, output, *, seed):
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("RT4 source checkpoint SHA256 mismatch")
        stream.seek(0)
        original, _ = ur.load_checkpoint(stream)
    arch = original.config["trunk"]
    if (arch["enc_layers"], arch["xattn_layers"]) != (4, 4):
        raise ValueError("expected four RT4 encoder and cross-attention layers")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = ur.build(dict(arch, enc_layers=6, xattn_layers=6), original.config["readout"])
    weights = model.state_dict()
    original_weights = original.state_dict()
    weights.update(original_weights)
    model.load_state_dict(weights, strict=True)
    with torch.no_grad():
        for i in range(4, 6):
            enc = model.trunk.encoder.layers[i]
            # Only the residual output projections start at zero so gradients can open each branch.
            for projection in (enc.self_attn.out_proj, enc.linear2, model.trunk.xattn[i].o, model.trunk.ff[i][-1]):
                projection.weight.zero_()
                projection.bias.zero_()
    with tempfile.NamedTemporaryFile(dir=output.parent) as staged:
        torch.save(dict(schema=ur.CKPT_SCHEMA, config=model.config, model=model.state_dict(),
                        initialization=dict(source_sha256=digest, depth_seed=seed)), staged)
        staged.flush()
        os.link(staged.name, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    deepen(args.source, args.source_sha256, args.output, seed=args.seed)

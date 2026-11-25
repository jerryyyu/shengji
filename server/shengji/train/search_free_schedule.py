"""Checkpoint a fixed-trunk candidate-head fit at each completed training shard.

Run from server with python -m shengji.train.search_free_schedule --help.
The sums file uses sha256sum format with candidate shard basenames. The served
readout package supplies the exact fixed weights for training and shared export.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path

from . import belief_seq as bs
from . import search_free_head as trainer
from . import unified_seq as us


def _entries(args):
    sums = {}
    for line in args.candidate_sums.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix("*")
        if name in sums or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid or repeated candidate digest")
        sums[name] = digest
    entries = bs.extract_entries(args.data, "train", exclude_seed_windows=args.exclude_seed_window)
    names = [trainer.candidate_name(e) for e in entries]
    if not entries or len(set(names)) != len(entries):
        raise ValueError("empty or duplicate training shard selection")
    for e, name in zip(entries, names):
        e["candidate_sha256"] = sums[name]
    return entries


def _fit(args, entries):
    import numpy as np
    import torch
    from ..ai.unified_readout_numpy import load_unified_readout_numpy

    settings = dict(version=1, base=args.sha256, entries=entries, epochs=args.epochs, seed=args.seed,
                    lr=args.lr, threads=args.threads, candidate_target=args.candidate_target)
    recipe = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    checkpoint = args.out / "checkpoint.pt"
    package = args.out / "head.npz"
    saved = torch.load(checkpoint, weights_only=True, map_location="cpu") if checkpoint.exists() else None
    if saved is not None and saved["recipe"] != recipe:
        raise ValueError("checkpoint belongs to a different training recipe")
    total = len(entries) * args.epochs
    if saved and (not 1 <= saved["next_shard"] <= total or saved["decisions"] < 0):
        raise ValueError("invalid checkpoint progress")
    if package.exists() and (not saved or saved["next_shard"] != total):
        raise ValueError("existing head without completed training checkpoint")
    served = load_unified_readout_numpy(args.base, args.sha256)
    model = us.build_unified(served.config["trunk"]).eval()
    weights = {f"trunk.{k}": v for k, v in served.trunk.w.items()}
    weights.update(served.h)
    model.load_state_dict({k: torch.from_numpy(v.copy()) for k, v in weights.items()})
    model.requires_grad_(False)
    torch.manual_seed(args.seed)
    head = trainer.build_head(model.config["trunk"])
    opt = torch.optim.AdamW(head.parameters(), lr=args.lr)
    cursor = decisions = 0
    if saved is not None:
        head.load_state_dict(saved["head"])
        opt.load_state_dict(saved["optimizer"])
        cursor, decisions = saved["next_shard"], saved["decisions"]
    verified = bs._Verified()
    for epoch in range(cursor // len(entries), args.epochs):
        order = np.random.default_rng([args.seed, epoch]).permutation(len(entries))
        for i in order[cursor % len(entries):]:
            decisions += trainer.fit_shard(model, head, opt, entries[i], args.candidates, verified,
                                           candidate_target=args.candidate_target)
            cursor += 1
            tmp = checkpoint.with_suffix(".tmp")
            torch.save(dict(recipe=recipe, head=head.state_dict(), optimizer=opt.state_dict(),
                            next_shard=cursor, decisions=decisions), tmp)
            os.replace(tmp, checkpoint)
            print(f"shards={cursor}/{total} decisions={decisions}", flush=True)
    if not decisions:
        raise ValueError("training selection contains no candidate ballots")
    if package.exists():
        from . import search_free_play as sf
        existing = sf.load_package(package, shared_unified=served)
        if (not existing.requires_shared_trunk or existing.metadata.get("recipe") != recipe
                or any(not np.array_equal(existing.c[k], v.detach().numpy()) for k, v in head.state_dict().items())):
            raise ValueError("existing head differs from the completed checkpoint")
        return existing.package_sha256
    return trainer.export(package, model, head, {"recipe": recipe, "decisions": decisions}, shared_unified=served)


def main(argv=None):
    import torch

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--data", action="append", required=True)
    p.add_argument("--exclude-seed-window", action="append", type=bs.seed_window, default=[])
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--candidate-sums", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--epochs", type=int, required=True)
    p.add_argument("--lr", type=float, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--threads", type=int, required=True)
    p.add_argument("--candidate-target", type=int, default=128)
    args = p.parse_args(argv)
    if min(args.epochs, args.threads, args.candidate_target) < 1 or args.seed < 0 or not (0 < args.lr < math.inf):
        p.error("invalid training dimensions, seed or learning rate")
    entries = _entries(args)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        torch.set_num_threads(args.threads)
        print(_fit(args, entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

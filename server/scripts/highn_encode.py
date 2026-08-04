"""Encode the high-N corpus into npz shards for training.

The corpus stores REBUILDABLE raw states, which is what makes it re-usable —
but training needs tensors, so encode once here rather than inside the training
loop.

The target is the ABSOLUTE 240-world mean: the expected outcome of playing a
candidate when the heuristic finishes the round, from the acting team's
perspective. It is raw-point `Q^H(s,a)`, deliberately not `max_a Q`, but also
not signed level utility or a generic state value.

Absolute scale matters. v11pair was trained on WITHIN-decision differences, so
adding any per-state constant left its loss unchanged and its cross-state scale
was never identified. These targets provide an anchor on the corpus's own
state/action/continuation distribution; using the result elsewhere still
requires an explicit contract match.

Each row also carries an inverse-variance weight from the marginal SE, so
well-resolved states count for more than noisy ones.

    uv run python scripts/highn_encode.py [in.jsonl] [out_dir] [shard_size]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, ".")

from scripts.highn_analyze import rebuild            # noqa: E402
from shengji.rl.encode import (ACT_DIM, ENC_VERSION,  # noqa: E402
                               OBS_DIM, encode_action, encode_obs)

VALUE_SCALE = 100.0     # same normalisation the distillation trainer uses


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "rl_data/highn_corpus_all.jsonl"
    out = sys.argv[2] if len(sys.argv) > 2 else "rl_data/highn_enc"
    shard = int(sys.argv[3]) if len(sys.argv) > 3 else 2500
    os.makedirs(out, exist_ok=True)

    obs_l, act_l, off, val, wt, meta = [], [], [0], [], [], []
    written = skipped = 0

    def flush(idx):
        nonlocal obs_l, act_l, off, val, wt
        if not obs_l:
            return
        np.savez_compressed(
            f"{out}/shard_{idx:05d}.npz",
            obs=np.stack(obs_l).astype(np.float32),
            actions=np.stack(act_l).astype(np.float32),
            offsets=np.array(off, np.int64),
            value=np.array(val, np.float32),        # ABSOLUTE, scaled
            weight=np.array(wt, np.float32),        # inverse-variance
            enc_version=np.int32(ENC_VERSION),
            obs_dim=np.int32(OBS_DIM), act_dim=np.int32(ACT_DIM))
        obs_l, act_l, off, val, wt = [], [], [0], [], []

    for i, line in enumerate(open(src)):
        rec = json.loads(line)
        try:
            rnd, seat = rebuild(rec)
            ob = encode_obs(rnd, seat)
            enc = [encode_action(list(c), rnd) for c in rec["candidates"]]
        except Exception:
            skipped += 1
            continue
        if len(enc) != len(rec["mean"]):
            skipped += 1
            continue
        obs_l.append(np.asarray(ob, np.float32))
        act_l.extend(np.asarray(e, np.float32) for e in enc)
        off.append(off[-1] + len(enc))
        for m, se in zip(rec["mean"], rec["stderr"]):
            val.append(m / VALUE_SCALE)
            # Inverse variance, floored so a single lucky state cannot dominate.
            wt.append(1.0 / max(se, 0.25) ** 2)
        written += 1
        if written % shard == 0:
            flush(written // shard)
            print(f"  {written:,} states encoded", flush=True)
    flush(written // shard + 1)
    # Count rows from the shards, not from the buffer: the buffer is empty
    # after the final flush, so the old message always printed 0 rows.
    import glob
    rows = sum(len(np.load(f)["value"]) for f in glob.glob(f"{out}/*.npz"))
    print(f"done: {written:,} states encoded, {skipped} skipped, "
          f"{rows:,} (state,action) rows -> {out}")
    if written < 1000:
        print("NOTE: that is a small corpus — check you passed the file you "
              "meant. A misplaced rsync once left the 845-state partial here "
              "while the 20k corpus sat in the repo root.")


if __name__ == "__main__":
    main()

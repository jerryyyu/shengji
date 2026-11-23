"""Compare the selected Torch checkpoint and served NumPy package on calibration rows."""
import argparse
import json
from pathlib import Path
import sys


TOLERANCE = 2e-3
_FLEET = Path.home() / "fleet"
_ARCHIVE = _FLEET / "cloud-archive/codex-20261106/root"
_STORE_MAP = [
    f"{_ARCHIVE}/codex-g2-belief-perf-v1@/root/={_FLEET}/perf-archive/root/",
    f"{_ARCHIVE}/codex-second100k-belief-perf-v1@/root/={_FLEET}/perf-archive/root/",
    f"/root/={_FLEET}/claude-g4/inputs/cloud/root/",
]


def measure_parity(checkpoint, package, data, requested):
    import numpy as np
    import torch

    from shengji.ai import unified_numpy as un, unified_readout_numpy as rn
    from shengji.train import belief_seq as bs, unified_readout as ur, unified_seq as us

    if requested <= 0:
        raise ValueError("parity row request must be positive")
    torch.set_num_threads(2)
    model, _ = ur.load_checkpoint(checkpoint)
    numpy_model = rn.load_unified_readout_numpy(package)
    entries = us.entries_for([data], "calib", exclude_seed_windows=())
    if not entries:
        raise ValueError("no calibration entries for parity")
    index = us.OutcomeIndex(us.parse_store_map(_STORE_MAP))
    part = us.load_unified_part(entries[0], bs._Verified(), index)
    first = next(bs.round_batches(part, 8, None), None)
    if first is None or not len(first[1]):
        raise ValueError("no calibration rows for parity")
    rids, rows = first
    batch = ur.make_batch(part, rids, rows)
    with torch.no_grad():
        out = model(us.to_device(batch, "cpu"))
    belief = out["belief"].numpy()
    value = out["leaf_value"].numpy()
    reply = out["leaf_reply"].numpy()
    worst = {"belief": 0.0, "value": 0.0, "reply": 0.0}
    sample = np.random.default_rng(0).choice(len(rows), size=min(requested, len(rows)), replace=False)
    for index in sample:
        i = int(index)
        inp = un.batch_inputs(batch, i, with_play=False)
        enc = numpy_model.trunk.encode_history(inp)
        q, g = numpy_model.card_states(inp, enc)
        leaves = np.nonzero(batch["leaf_row"] == i)[0]
        cache = numpy_model.decision_cache(q, g)
        planes, scalars = batch["leaf_planes"][leaves], batch["leaf_scalars"][leaves]
        comparisons = {
            "belief": (numpy_model.belief_logits(inp, enc), belief[i]),
            "value": (numpy_model.leaf_value_logits(cache, planes, scalars), value[leaves]),
            "reply": (numpy_model.leaf_reply_logits(cache, planes, scalars), reply[leaves]),
        }
        for name, (actual, expected) in comparisons.items():
            if actual.shape != expected.shape or not actual.size:
                raise ValueError(f"row {i}: {name} parity shape mismatch or empty outputs")
            error = np.abs(actual - expected)
            if not np.isfinite(error).all():
                raise ValueError(f"row {i}: non-finite {name} parity error")
            worst[name] = max(worst[name], float(error.max()))
    return {"rows": len(sample), "max_abs_diff": worst,
            "parity": "OK" if all(v < TOLERANCE for v in worst.values()) else "FAIL",
            "package": numpy_model.package_sha256}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("package")
    parser.add_argument("data")
    parser.add_argument("rows", type=int)
    args = parser.parse_args(argv)
    try:
        report = measure_parity(args.checkpoint, args.package, args.data, args.rows)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"parity refused: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(report, allow_nan=False))
    return 0 if report["parity"] == "OK" else 3


if __name__ == "__main__":
    sys.exit(main())

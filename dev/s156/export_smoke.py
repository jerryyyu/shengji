"""Export the completed medium smoke checkpoint and validate its paired serving packages."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from shengji.ai import belief_numpy, unified_readout_numpy as readout
from shengji.train import unified_readout as trainer


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export(root, parity_reader, calib, expected_rows=124):
    train = root / "smoke/train"
    ckpt = train / "best.pt"
    ck_sha = sha(ckpt)
    last = (train / "status.log").read_text().splitlines()[-1].split()
    if last[1:] != ["UTR", "DONE", f"best={ckpt}", f"sha256={ck_sha}"]:
        raise ValueError("missing exact checkpoint terminal")
    settings = json.loads((train / "run.json").read_text())
    if settings["device"] != "mps" or settings["max_train_rows"] != 120000:
        raise ValueError("wrong smoke device or training cap")
    out = root / "packages"
    out.mkdir()
    value, belief = out / "value.npz", out / "belief.npz"
    rc = trainer.main(["export", "--ckpt", str(ckpt), "--out", str(value),
                       "--temperature", "1.0189738579997958", "--note", "SZ2 M2 smoke"])
    if rc:
        raise ValueError(f"export failed: {rc}")
    model = readout.load_unified_readout_numpy(value)
    if model.metadata["source_checkpoint_sha256"] != ck_sha:
        raise ValueError("exported package names a different checkpoint")
    belief_sha = readout.belief_package(model, belief)
    trunk = belief_numpy.load_belief_numpy(belief, belief_sha)
    if trunk.metadata["source_unified_package"] != model.package_sha256:
        raise ValueError("belief package has a different value-package parent")
    result = subprocess.run([sys.executable, "-B", str(parity_reader), str(ckpt),
                             str(value), str(calib), "150"], check=True, stdout=subprocess.PIPE, text=True)
    parity = json.loads(result.stdout)
    errors = parity["max_abs_diff"]
    if (parity["package"] != model.package_sha256 or parity["parity"] != "OK" or parity["rows"] != expected_rows
            or set(errors) != {"belief", "value", "reply"}
            or not all(math.isfinite(x) and 0 <= x < 2e-3 for x in errors.values())):
        raise ValueError(f"parity witness failed: {parity}")
    with (out / "parity.json").open("x") as stream:
        json.dump(dict(parity, checkpoint_sha256=ck_sha, belief_sha256=belief_sha), stream, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "parity_reader", "calib"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    export(args.root.resolve(), args.parity_reader, args.calib)

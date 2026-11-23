"""Export and check the selected checkpoint of one SZ2 arm."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from sz2_cache_arm import FLEET, JOINT, RECIPE, RECIPE_SHA, arm_inputs
from sz2_export_parity import TOLERANCE

POLISH = FLEET / "codex-sz2-polish-v1"
EXPORT = FLEET / "codex-sz2-export-v1"
PARITY_SCRIPT = Path(__file__).resolve().with_name("sz2_export_parity.py")
PARITY_DATA = FLEET / "cloud-archive/codex-20261106/root/codex-g2-belief-cloud-v1/partitions/part-00of32"
PARITY_ROWS = 124
PARITY_REQUEST = 150
TEMPERATURE = 1.0189738579997958


def file_sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def selected_checkpoint(polish, checkpoint, joint_sha):
    status = (polish / "status.log").read_text().splitlines()
    done = re.fullmatch(r"\S+ POLISH DONE best_epoch=([012]) calib .+ sha256=([0-9a-f]{64})",
                        status[-1]) if status else None
    if not done:
        raise ValueError("missing polish terminal")
    epoch = int(done[1])
    selected = polish / "selected.pt"
    winner = polish / "best.pt" if epoch else checkpoint
    if selected.is_symlink() or not selected.is_file() or not selected.samefile(winner):
        raise ValueError("selected checkpoint does not match the polish winner")
    expected = done[2] if epoch else joint_sha
    if epoch and file_sha(selected) != expected:
        raise ValueError("selected checkpoint differs from the polish terminal")
    return selected, expected, epoch


def check_parity(report, package_sha, rows):
    if (not isinstance(report, dict) or report.get("parity") != "OK"
            or report.get("package") != package_sha
            or type(report.get("rows")) is not int or report["rows"] != rows):
        raise ValueError("parity does not identify the exported package and full sample")
    metrics = report.get("max_abs_diff")
    if (not isinstance(metrics, dict) or set(metrics) != {"belief", "value", "reply"}
            or any(type(delta) not in (int, float) or not math.isfinite(delta)
                   or not 0 <= delta < TOLERANCE for delta in metrics.values())):
        raise ValueError("parity errors exceed tolerance or are missing")


def export_arm(joint, arm, polish_root, output, recipe_path, recipe_sha,
               parity_data, parity_rows):
    from shengji.ai import unified_readout_numpy as rn
    from shengji.train import unified_readout

    checkpoint, identity, _ = arm_inputs(joint, arm, polish_root, recipe_path, recipe_sha)
    selected, selected_sha, epoch = selected_checkpoint(identity, checkpoint, identity.name.split("-", 1)[0])
    if not parity_data.is_dir():
        raise ValueError("missing parity data")

    out = output / arm / identity.name
    out.mkdir(parents=True, exist_ok=False)
    package = out / "cand.npz"
    rc = unified_readout.main(["export", "--ckpt", str(selected), "--out", str(package),
                               "--temperature", str(TEMPERATURE), "--note", f"SZ2 {arm}"])
    if rc:
        return rc
    model = rn.load_unified_readout_numpy(package)
    if model.metadata.get("source_checkpoint_sha256") != selected_sha:
        raise ValueError("export package differs from the selected checkpoint")
    belief_sha = rn.belief_package(model, out / "cand-belief.npz")
    env = {**os.environ, "OMP_NUM_THREADS": "2"}
    with (out / "parity.err").open("wb") as stderr:
        result = subprocess.run([sys.executable, "-B", str(PARITY_SCRIPT), str(selected), str(package),
                                 str(parity_data), str(PARITY_REQUEST)],
                                cwd=out, env=env, check=True, stdout=subprocess.PIPE, stderr=stderr,
                                timeout=600)
    parity = json.loads(result.stdout)
    check_parity(parity, model.package_sha256, parity_rows)
    parity.update(belief_sha256=belief_sha, selected_checkpoint_sha256=selected_sha, best_epoch=epoch)
    pending = out / "parity.json.tmp"
    pending.write_text(json.dumps(parity, allow_nan=False) + "\n")
    os.replace(pending, out / "parity.json")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=("S", "M"))
    try:
        return export_arm(JOINT, parser.parse_args().arm, POLISH, EXPORT, RECIPE, RECIPE_SHA,
                          PARITY_DATA, PARITY_ROWS)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"export refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

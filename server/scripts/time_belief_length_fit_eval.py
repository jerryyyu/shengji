"""Measure one joint-length fit and bounded held-out evaluation in fresh processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("train-extract", "test-extract", "cohort", "belief-package", "output-dir"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--belief-sha256", required=True)
    parser.add_argument("--cohort-sha256", required=True)
    args = parser.parse_args(argv)
    cohort_bytes = args.cohort.read_bytes()
    if hashlib.sha256(cohort_bytes).hexdigest() != args.cohort_sha256:
        raise ValueError("wrong timing cohort")
    members = json.loads(cohort_bytes)["deals"]
    if len(members) != 1 or type(members[0]["rows"]) is not int or not 1 <= members[0]["rows"] <= 100:
        raise ValueError("pilot requires one deal with at most 100 decisions")

    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    server = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    out.mkdir()
    cohort = out / "cohort.json"
    cohort.write_bytes(cohort_bytes)
    checkpoint = out / "length.pt"
    start = monotonic()

    def run(module, flags):
        return subprocess.run([sys.executable, "-m", "shengji.train." + module, *flags],
                              cwd=server, env=env, text=True, stdout=subprocess.PIPE,
                              timeout=max(0, 900 - (monotonic() - start)), check=True).stdout

    run("belief_lengths", ["--extract", args.train_extract.resolve(), "--out", checkpoint,
                           "--seed", "164", "--width", "64", "--steps", "1", "--rounds-per-batch", "1"])
    fit_seconds = monotonic() - start
    output = run("belief_length_eval", [
        "--extract", args.test_extract.resolve(), "--length-checkpoint", checkpoint,
        "--belief-package", args.belief_package.resolve(), "--belief-sha256", args.belief_sha256,
        "--cohort", cohort, "--seed", "164", "--ll-replicates", "2",
        "--ll-max-draws", "8", "--timing-only",
    ])
    elapsed = monotonic() - start
    result = json.loads(output)
    timing_fields = {"decisions", "deals", "worlds_per_void_arm", "evaluation_seconds", "log_loss_seconds",
                     "scored_decisions", "worlds_drawn", "maximum_worlds", "draw_limit_per_row_per_replicate",
                     "replicates", "unresolved_copy_observations"}
    if (set(result) != timing_fields or result["decisions"] != members[0]["rows"] or result["deals"] != 1
            or result["worlds_per_void_arm"] != 64 or result["replicates"] != 2
            or result["draw_limit_per_row_per_replicate"] != 8
            or not 0 < result["worlds_drawn"] <= result["maximum_worlds"] <= 16 * result["decisions"]):
        raise ValueError("evaluation did not complete the bounded timing workload")
    report = dict(fit_process_seconds=fit_seconds, fit_eval_process_seconds=elapsed, timing=result)
    temporary = out / "timing.partial"
    with temporary.open("x") as stream:
        json.dump(report, stream, allow_nan=False)
        stream.write("\n")
    temporary.rename(out / "timing.json")


if __name__ == "__main__":
    main()

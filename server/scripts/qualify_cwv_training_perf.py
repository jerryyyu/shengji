"""Bounded same-recipe training A/B/B/A. Dry-run by default; no fleet control.

Supply JSON kwargs for train_cwv.train using already-opened DEV data, a shared
prewarmed cache, and an existing public_head. Each arm is a fresh process.
This measures training/receipt engineering, not model quality. Run only in an
isolated host window. Results remain available if a later arm fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def recipe(path):
    kw = json.loads(Path(path).read_text())
    if not isinstance(kw, dict) or any(k in kw for k in ("out", "log", "argv")):
        raise ValueError("config must be train kwargs without out/log/argv")
    for key, ceiling in (("epochs", 2), ("limit_clusters", 128)):
        if type(kw.get(key)) is not int or not 1 <= kw[key] <= ceiling:
            raise ValueError(f"explicit {key} must be within 1..{ceiling}")
    if not kw.get("cache_dir") or not kw.get("public_head"):
        raise ValueError("provide a shared prewarmed cache_dir and existing public_head")
    if kw.get("target", "realised") != "realised":
        raise ValueError("qualification holds the target fixed at realised")
    return kw


def checkpoint_fingerprint(path):
    from shengji.train.train_cwv import load_cwv_checkpoint
    model, meta, aux = load_cwv_checkpoint(path)
    digest = hashlib.sha256()
    for prefix, module in (("model", model), ("aux", aux)):
        if module is None:
            continue
        for name, tensor in sorted(module.state_dict().items()):
            a = tensor.detach().cpu().contiguous().numpy()
            digest.update(json.dumps([prefix, name, str(a.dtype), a.shape]).encode())
            digest.update(a.tobytes())
    return {"tensor_sha256": digest.hexdigest(), "epoch": meta["epoch"]}


def cache_inventory(path):
    root = Path(path)
    if not root.is_dir():
        raise ValueError("cache_dir must already exist and be prewarmed")
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*.npz")}


def child(config, out):
    import torch
    from shengji.train.train_cwv import train
    kw = recipe(config)
    start = time.perf_counter()
    result = train(out=out / "train", **kw)
    # Finish queued GPU work before recording wall; child peak RSS is not GPU memory.
    if kw.get("device") == "mps":
        torch.mps.synchronize()
    elif str(kw.get("device", "")).startswith("cuda"):
        torch.cuda.synchronize()
    wall = time.perf_counter() - start
    usage = resource.getrusage(resource.RUSAGE_SELF)
    descendants = resource.getrusage(resource.RUSAGE_CHILDREN)
    # Capture RNG before reloading checkpoints for comparison.
    rng = hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()
    checkpoints = [out / "train" / "best.pt", *sorted((out / "train" / "checkpoints").glob("epoch-*.pt"))]
    report = {
        "wall_seconds": wall,
        "cpu_seconds_including_reaped_children": usage.ru_utime + usage.ru_stime + descendants.ru_utime + descendants.ru_stime,
        "parent_peak_rss_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "torch_cpu_rng_sha256": rng,
        "checkpoints": {str(p.relative_to(out / "train")): checkpoint_fingerprint(p) for p in checkpoints},
        "epoch_train_seconds": [e["train_secs"] for e in result["epochs"]],
        "candidate_report_seconds": result["final"]["test"]["ranking"]["secs"],
        "note": "RSS excludes child/GPU peaks; report-score batching is tolerance-equivalent, not bit-exact",
    }
    (out / "measurement.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run", action="store_true")
    p.add_argument("--arm-timeout-seconds", type=int, default=900)
    p.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()
    if not 1 <= args.arm_timeout_seconds <= 3600:
        p.error("arm timeout must be in 1..3600 seconds")
    config = str(Path(args.config).resolve())
    kw = recipe(config)
    out = Path(args.out).resolve()
    if args.child:
        child(config, out)
        return
    plan = {"recipe": kw, "order": ["control", "optimized", "optimized", "control"], "out": str(out)}
    print(json.dumps(plan, indent=2), flush=True)
    if not args.run:
        return
    cache_before = cache_inventory(kw["cache_dir"])
    out.mkdir(parents=True, exist_ok=False)
    # Frozen local copy: no mid-benchmark edits to caller config.
    frozen = out / "recipe.json"
    frozen.write_text(json.dumps(kw, sort_keys=True, indent=2) + "\n")
    for i, arm in enumerate(plan["order"]):
        arm_out = out / f"{i}-{arm}"
        arm_out.mkdir()
        env = dict(os.environ, SHENGJI_CWV_LOSS_SYNC_EVERY="1" if arm == "control" else "32",
                   SHENGJI_CWV_BATCHED_CANDIDATES="0" if arm == "control" else "1")
        with (arm_out / "run.log").open("x") as log:
            # Start a private group so expiry can stop decode workers too.
            proc = subprocess.Popen([sys.executable, __file__, "--config", str(frozen), "--out", str(arm_out), "--child"],
                                    env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=args.arm_timeout_seconds)
            except BaseException:
                import signal
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise
            if code:
                raise subprocess.CalledProcessError(code, proc.args)
        if cache_inventory(kw["cache_dir"]) != cache_before:
            raise RuntimeError("cache changed during benchmark; retain arm, prewarm cache before a fresh timing run")
    reports = [json.loads((out / f"{i}-{arm}" / "measurement.json").read_text()) for i, arm in enumerate(plan["order"])]
    def same(a, b):
        return (a["checkpoints"] == b["checkpoints"]
                and a["torch_cpu_rng_sha256"] == b["torch_cpu_rng_sha256"])
    equal = all(same(r, reports[0]) for r in reports)
    summary = {"exact_checkpoint_and_cpu_rng_parity": equal, "arms": reports,
               "control_repeatable": same(reports[0], reports[3]),
               "optimized_repeatable": same(reports[1], reports[2]),
               "control_mean_wall": (reports[0]["wall_seconds"] + reports[3]["wall_seconds"]) / 2,
               "optimized_mean_wall": (reports[1]["wall_seconds"] + reports[2]["wall_seconds"]) / 2}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not equal:
        raise RuntimeError("checkpoint/RNG mismatch: retain evidence; do not claim decision-preserving training")


if __name__ == "__main__":
    main()

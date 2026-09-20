"""Bounded same-recipe training A/B/B/A. Dry-run by default; no fleet control.

Supply JSON kwargs for train_cwv.train using already-opened DEV data, a shared
prewarmed cache, and an existing public_head. Each arm is a fresh process.
This measures training/receipt engineering, not model quality. Run only in an
isolated host window. Results remain available if a later arm fails.

Use --comparison validation-packing for the opt-in epoch outcome-evaluation
optimization: both arms retain candidate batching and sync32. The old default
measures those older optimizations instead and cannot attribute a packing gain.
Use a dedicated recipe cache, not a fleet-wide cache: inventory checks traverse
the entire supplied directory. Bounds remain two epochs / 128 DEV clusters;
this does not by itself qualify full-corpus throughput or downstream strength.
Policy artifacts are independently bounded at 16 chunks and 256 MiB total
compressed + declared uncompressed array + flat metadata bytes, because a
per-pass policy_rows_limit does not bound startup verification.
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
import zipfile


POLICY_INPUT_BYTES = 256 * 1024**2


def check_policy_input_budget(kw):
    """Bound startup verification too, using file/ZIP metadata, not row limits.

    No array decode, full hashing, corpus sampling, or input mutation. Normal
    training loaders still perform all schema/hash/exposure validation later.
    """
    total = 0
    for key in ('policy_rows', 'policy_eval'):
        if not kw.get(key):
            continue
        root = Path(kw[key])
        if key == 'policy_rows' and root.is_dir():
            manifest = root/'manifest.json'
            if manifest.stat().st_size > 1024**2:
                raise ValueError('policy input manifest exceeds qualification budget')
            chunks = json.loads(manifest.read_text()).get('chunks', [])
            if not 1 <= len(chunks) <= 16:
                raise ValueError('qualification requires 1..16 policy chunks, not full corpus')
            paths = []
            for chunk in chunks:
                path = (root/chunk['file']).resolve()
                if path.parent != root.resolve():
                    raise ValueError('policy chunk must be directly inside its artifact directory')
                paths.append(path)
        else:
            paths = [Path(str(root)+'.npz')]
            total += Path(str(root)+'.meta.jsonl').stat().st_size
        for path in paths:
            total += path.stat().st_size
            if total > POLICY_INPUT_BYTES:
                raise ValueError('policy inputs exceed qualification byte budget')
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > 128:
                    raise ValueError('policy archive exceeds qualification member budget')
                total += sum(member.file_size for member in members)
            if total > POLICY_INPUT_BYTES:
                raise ValueError('policy inputs exceed qualification byte budget')


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
    check_policy_input_budget(kw)
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


def arm_recipe(config, comparison, arm):
    kw = recipe(config)
    if comparison == "validation-packing":
        if kw.get("arch", "mlp") != "mlp":
            raise ValueError("validation packing requires MLP")
        if kw.get("pack_validation_shards", False):
            raise ValueError("qualifier owns pack_validation_shards; omit it from recipe")
        kw["pack_validation_shards"] = arm == "optimized"
    return kw


def arm_env(comparison, arm):
    old_baseline = comparison == "batching-sync" and arm == "control"
    return dict(os.environ,
                SHENGJI_CWV_LOSS_SYNC_EVERY="1" if old_baseline else "32",
                SHENGJI_CWV_BATCHED_CANDIDATES="0" if old_baseline else "1")


def child(config, out, *, comparison="batching-sync", arm="optimized"):
    import torch
    from shengji.train.train_cwv import train
    kw = arm_recipe(config, comparison, arm)
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
        "comparison": comparison, "arm": arm,
        "wall_seconds": wall,
        "cpu_seconds_including_reaped_children": usage.ru_utime + usage.ru_stime + descendants.ru_utime + descendants.ru_stime,
        "parent_peak_rss_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "torch_cpu_rng_sha256": rng,
        "checkpoints": {str(p.relative_to(out / "train")): checkpoint_fingerprint(p) for p in checkpoints},
        "epoch_train_seconds": [e["train_secs"] for e in result["epochs"]],
        "epoch_loop_seconds": [e["secs"] for e in result["epochs"]],
        "epoch_validation_stages": [e["val"]["stage_wall_seconds"] for e in result["epochs"]],
        "candidate_report_seconds": result["final"]["test"]["ranking"]["secs"],
        "note": "RSS excludes child/GPU peaks; report-score batching is tolerance-equivalent, not bit-exact",
    }
    (out / "measurement.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run", action="store_true")
    p.add_argument("--warmup", action="store_true",
                   help="run one bounded full control recipe before timing; retain it separately")
    p.add_argument("--arm-timeout-seconds", type=int, default=900)
    p.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--comparison", choices=("batching-sync", "validation-packing"),
                   default="batching-sync",
                   help="validation-packing holds candidate batching and sync32 on in both arms")
    p.add_argument("--arm", choices=("control", "optimized"), default="optimized",
                   help=argparse.SUPPRESS)
    args = p.parse_args()
    if not 1 <= args.arm_timeout_seconds <= 3600:
        p.error("arm timeout must be in 1..3600 seconds")
    config = str(Path(args.config).resolve())
    kw = recipe(config)
    # Validate both treatments even in dry-run, before creating any output.
    for arm in ("control", "optimized"):
        arm_recipe(config, args.comparison, arm)
    out = Path(args.out).resolve()
    if args.child:
        child(config, out, comparison=args.comparison, arm=args.arm)
        return
    plan = {"recipe": kw, "order": ["control", "optimized", "optimized", "control"],
            "comparison": args.comparison,
            "warmup": args.warmup, "out": str(out)}
    print(json.dumps(plan, indent=2), flush=True)
    if not args.run:
        return
    cache_before = cache_inventory(kw["cache_dir"])
    out.mkdir(parents=True, exist_ok=False)
    # Frozen local copy: no mid-benchmark edits to caller config.
    frozen = out / "recipe.json"
    frozen.write_text(json.dumps(kw, sort_keys=True, indent=2) + "\n")
    stages = [(f"{i}-{arm}", arm) for i, arm in enumerate(plan["order"])]
    if args.warmup:
        stages.insert(0, ("warmup", "control"))
    for name, arm in stages:
        arm_out = out / name
        arm_out.mkdir()
        env = arm_env(args.comparison, arm)
        with (arm_out / "run.log").open("x") as log:
            # Start a private group so expiry can stop decode workers too.
            proc = subprocess.Popen([sys.executable, __file__, "--config", str(frozen), "--out", str(arm_out), "--child",
                                     "--comparison", args.comparison, "--arm", arm],
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
        if name == "warmup":
            # Preparing only state stores misses validation/test candidate caches.
            # The exact recipe prepares all consumers, outside the timed ABBA.
            cache_before = cache_inventory(kw["cache_dir"])
        elif cache_inventory(kw["cache_dir"]) != cache_before:
            raise RuntimeError("cache changed during benchmark; retain arm, prewarm cache before a fresh timing run")
    reports = [json.loads((out / f"{i}-{arm}" / "measurement.json").read_text()) for i, arm in enumerate(plan["order"])]
    def same(a, b):
        return (a["checkpoints"] == b["checkpoints"]
                and a["torch_cpu_rng_sha256"] == b["torch_cpu_rng_sha256"])
    equal = all(same(r, reports[0]) for r in reports)
    summary = {"exact_checkpoint_and_cpu_rng_parity": equal, "arms": reports,
               "warmup": (json.loads((out / "warmup" / "measurement.json").read_text())
                          if args.warmup else None),
               "control_repeatable": same(reports[0], reports[3]),
               "optimized_repeatable": same(reports[1], reports[2]),
               "control_mean_wall": (reports[0]["wall_seconds"] + reports[3]["wall_seconds"]) / 2,
               "optimized_mean_wall": (reports[1]["wall_seconds"] + reports[2]["wall_seconds"]) / 2}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not equal:
        raise RuntimeError("checkpoint/RNG mismatch: retain evidence; do not claim decision-preserving training")


if __name__ == "__main__":
    main()

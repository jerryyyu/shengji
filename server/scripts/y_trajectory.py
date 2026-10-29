#!/usr/bin/env python3
"""Capture the singleton/confirmation policy with the deployed recipe's budgets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib


def recipe_environment(fly: Path, models: Path) -> dict[str, str]:
    env = tomllib.loads(fly.read_text())["env"]
    selected = {k: str(v) for k, v in env.items()
                if k.startswith(("SHENGJI_PV_", "SHENGJI_CWV_"))
                or k in ("SHENGJI_FAST", "SHENGJI_REQUIRE_VOIDS", "SHENGJI_BOT")}
    for key, value in list(selected.items()):
        if key.endswith("_CKPT"):
            if not value.startswith("/data/models/") or Path(value).name != value.removeprefix("/data/models/"):
                raise ValueError(f"unexpected model path for {key}")
            selected[key] = str(models.resolve() / Path(value).name)
    if selected.get("SHENGJI_PV_SERVING_BUDGET_SECONDS") != "3":
        raise ValueError("play budget must be 3 seconds")
    if selected.get("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS") != "2":
        raise ValueError("bury budget must be 2 seconds")
    if selected.get("SHENGJI_PV_WORLDS") != "64" or selected.get("SHENGJI_PV_CANDIDATES") != "8":
        raise ValueError("Y requires W64/K8")
    if any(selected.get(k, "0") != "0" for k in
           ("SHENGJI_PV_SINGLETON_CHALLENGER", "SHENGJI_PV_LEAD_CONFIRM")):
        raise ValueError("baseline already contains candidate overrides")
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--fly", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--seed-registry", type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    args, rest = parser.parse_known_args(argv)
    if any(a.split("=", 1)[0] in {
        "--policy", "--explore-rate", "--explore-k", "--round-mix",
        "--knob", "--widen", "--allow-seed-overlap", "--select-worlds",
        "--report-worlds", "--capture-full-legal-scores", "--capture-served-budget",
    } for a in rest):
        parser.error("policy, capture mode, sampling and exploration are fixed by this runner")
    selected = recipe_environment(args.fly, args.models)
    for key in list(os.environ):
        if key.startswith("SHENGJI_"):
            del os.environ[key]
    os.environ.update(selected)
    if not args.seed_registry.is_file():
        raise ValueError("an existing seed registry is required")
    os.environ["SHENGJI_SEED_WINDOWS"] = str(args.seed_registry.resolve())
    os.environ["SHENGJI_Y_CAPTURE_FLY_SHA256"] = hashlib.sha256(args.fly.read_bytes()).hexdigest()
    os.environ["SHENGJI_Y_CAPTURE_RUNNER_SHA256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from shengji.ai import registry
    from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries, singleton_registry_entries
    baseline = pv_registry_entries(**pv_env_recipe())
    expected = selected["SHENGJI_BOT"]
    if expected not in baseline:
        raise ValueError(f"fly baseline drift: {expected} not in {sorted(baseline)}")
    baseline[expected](seed=0)
    os.environ["SHENGJI_PV_SINGLETON_CHALLENGER"] = "1"
    os.environ["SHENGJI_PV_LEAD_CONFIRM"] = "32"
    entries = singleton_registry_entries(**pv_env_recipe())
    if len(entries) != 1:
        raise ValueError(f"ambiguous candidate: {sorted(entries)}")
    name, factory = next(iter(entries.items()))
    registry.REGISTRY.update(entries)
    bot = factory(seed=0)
    if bot.serving_budget_seconds != 3 or bot.bury_serving_budget_seconds != 2 or bot.lead_confirm != 32:
        raise ValueError("candidate lost serving budgets")
    print(json.dumps({"baseline": expected, "candidate": name,
                      "fly_sha256": hashlib.sha256(args.fly.read_bytes()).hexdigest(),
                      "play_seconds": 3, "bury_seconds": 2,
                      "environment": {k: v for k, v in os.environ.items() if k.startswith("SHENGJI_")}}, sort_keys=True), flush=True)
    if args.inspect:
        return 0
    from shengji.harvest.trajectory import main as generate
    return generate(rest + ["--policy", name, "--explore-rate", "0", "--explore-k", "0",
                            "--round-mix", "sampled", "--capture-served-budget"])


if __name__ == "__main__":
    raise SystemExit(main())

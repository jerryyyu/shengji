#!/usr/bin/env python3
"""Capture the unified bot's self-play with release 52's serving budgets.

The environment is ``y_trajectory.recipe_environment`` (fly.toml's [env], model paths mapped to
``--models``) with the belief package replaced by the one carrying the unified trunk and the
unified readout package named (``SHENGJI_PV_UNIFIED_CKPT`` / ``_SHA256``).  All four seats play
the registry's unified name, which must equal ``--expect-name``; capture, sampling and
exploration are fixed: served-budget capture, ``--round-mix sampled``, explore 0, cap 256.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
FIXED = {"--policy", "--explore-rate", "--explore-k", "--round-mix", "--knob", "--widen",
         "--allow-seed-overlap", "--select-worlds", "--report-worlds", "--cap",
         "--capture-full-legal-scores", "--capture-served-budget"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _y_trajectory():
    spec = importlib.util.spec_from_file_location("y_trajectory", HERE.with_name("y_trajectory.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--fly", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--unified", type=Path, required=True)
    parser.add_argument("--unified-sha256", required=True)
    parser.add_argument("--belief", type=Path, required=True)
    parser.add_argument("--belief-sha256", required=True)
    parser.add_argument("--expect-name", required=True)
    parser.add_argument("--seed-registry", type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    args, rest = parser.parse_known_args(argv)
    if rest[:1] == ["--"]:
        rest = rest[1:]
    if any(a.split("=", 1)[0] in FIXED for a in rest):
        parser.error("policy, capture mode, sampling and exploration are fixed by this runner")
    for path, want in ((args.unified, args.unified_sha256), (args.belief, args.belief_sha256)):
        if _sha(path) != want:
            raise SystemExit(f"{path}: sha256 {_sha(path)} != {want}")
    selected = _y_trajectory().recipe_environment(args.fly, args.models)
    selected["SHENGJI_PV_BELIEF_CKPT"] = str(args.belief.resolve())
    selected["SHENGJI_PV_BELIEF_SHA256"] = args.belief_sha256
    selected["SHENGJI_PV_UNIFIED_CKPT"] = str(args.unified.resolve())
    selected["SHENGJI_PV_UNIFIED_SHA256"] = args.unified_sha256
    for key in list(os.environ):
        if key.startswith("SHENGJI_"):
            del os.environ[key]
    os.environ.update(selected)
    if not args.seed_registry.is_file():
        raise SystemExit("an existing seed registry is required")
    os.environ["SHENGJI_SEED_WINDOWS"] = str(args.seed_registry.resolve())
    os.environ["SHENGJI_Y_CAPTURE_FLY_SHA256"] = _sha(args.fly)
    os.environ["SHENGJI_Y_CAPTURE_RUNNER_SHA256"] = _sha(HERE)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    sys.path.insert(0, str(HERE.parents[1]))
    from shengji.ai import registry
    from shengji.train.unified_serving import unified_name
    name = unified_name(selected["SHENGJI_BOT"], args.unified_sha256)
    if name != args.expect_name:
        raise SystemExit(f"derived name {name} != expected {args.expect_name}")
    if name not in registry.REGISTRY:
        raise SystemExit(f"unified name not registered: {name}")
    bot = registry.make_bot(name, seed=0)
    if (bot.policy_name != name or bot.serving_budget_seconds != 3 or bot.bury_serving_budget_seconds != 2
            or bot.lead_confirm or getattr(bot, "unified_sha256", None) != args.unified_sha256):
        raise SystemExit(f"unified bot drift: {bot.policy_name}")
    print(json.dumps({"policy": name, "served_name": selected["SHENGJI_BOT"],
                      "fly_sha256": _sha(args.fly), "play_seconds": 3, "bury_seconds": 2,
                      "explore_rate": 0, "round_mix": "sampled", "cap": 256,
                      "environment": {k: v for k, v in sorted(os.environ.items()) if k.startswith("SHENGJI_")}},
                     sort_keys=True), flush=True)
    if args.inspect:
        return 0
    from shengji.harvest.trajectory import main as generate
    return generate(rest + ["--cap", "256", "--policy", name, "--explore-rate", "0", "--explore-k", "0",
                            "--round-mix", "sampled", "--capture-served-budget"])


if __name__ == "__main__":
    raise SystemExit(main())

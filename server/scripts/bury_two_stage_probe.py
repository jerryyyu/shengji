"""DEV probe: latency of the wide bury's second stage and how often it overrules stage 1.

Builds the served bot from fly.toml's ``SHENGJI_PV_*`` env exactly as the
registry does (``pv_env_recipe`` -> ``pv_registry_entries`` -> factory), with the
package path mapped to a local copy, once per variant (``null`` = release 45,
otherwise `bury_two_stage.TwoStageConfig` keywords), and decides the bury on the
seeded DEV bury roots (`cwv_bury_diagnostic.capture_state`) in-process, under
the served 2 s bury budget.  Reports per variant the whole bury's wall seconds
(mean / p50 / p90 / max), stage 2's own seconds, how many decisions the stage
switched, how many did not complete (and why), and heuristic fallbacks.

    SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \\
    python scripts/bury_two_stage_probe.py --package /local/smv3out-491ee4bf.npz \\
        --roots 1000:1040 --out probe.json [--variants '[null, {}, {"tricks": 1}]']

Timing only, on this host; no strength claim.  The output is created
exclusively (an existing path is refused).
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shengji.engine import fast  # noqa: E402
from shengji.train import pv_search_policy as pv  # noqa: E402
from shengji.train.bury_two_stage import RECORD_KEY, TwoStageConfig  # noqa: E402
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state  # noqa: E402


def _quantile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _spread(values):
    return {"mean": statistics.mean(values), "p50": _quantile(values, 0.5),
            "p90": _quantile(values, 0.9), "max": max(values)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--package", required=True, help="local copy of the fly.toml SHENGJI_PV_CKPT package")
    p.add_argument("--fly-toml", default=str(SERVER.parent / "fly.toml"))
    p.add_argument("--roots", default="1000:1040", help="DEV bury-root indices, start:stop")
    p.add_argument("--variants", default='[null, {}]')
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    if a.out.exists():
        p.error(f"{a.out} exists; the probe never overwrites")
    start, stop = (int(x) for x in a.roots.split(":"))
    variants = json.loads(a.variants)
    env = {k: v for k, v in tomllib.loads(Path(a.fly_toml).read_text())["env"].items()
           if k.startswith("SHENGJI_PV_")}
    env["SHENGJI_PV_CKPT"] = a.package
    recipe = pv.pv_env_recipe(env)
    roots = list(range(start, stop))
    states = [reopen_state(capture_state(i)) for i in roots]
    result = {"schema": "bury-two-stage-probe-v1", "compiled_engine": bool(fast.activate()),
              "package": a.package, "roots": [start, stop], "variants": []}
    for variant in variants:
        r = dict(recipe)
        if variant is not None:
            r["bury_two_stage"] = TwoStageConfig(**variant)
        (name, factory), = pv.pv_registry_entries(**r).items()
        bot = factory(seed=0)
        warm = copy.deepcopy(states[0])
        bot.decide_bury(warm, warm.banker)              # load and warm, not measured
        rows = []
        for index, state in zip(roots, states):
            rnd = copy.deepcopy(state)
            t0 = time.perf_counter()
            bot.decide_bury(rnd, rnd.banker)
            wall = time.perf_counter() - t0
            record = bot.last_bury_record
            ts = record.get(RECORD_KEY)
            rows.append({"root": index, "wall": wall, "schema": record["schema"],
                         "picked": record.get("picked_index"),
                         "stage1_seconds": record.get("model_seconds"),
                         "two_stage": ts})
        summary = {"variant": variant, "name": name, "n": len(rows),
                   "wall": _spread([row["wall"] for row in rows]),
                   "heuristic_fallbacks": sum(row["schema"] != "cwv-bury-policy-v1" for row in rows)}
        stages = [row["two_stage"] for row in rows if row["two_stage"] is not None]
        if stages:
            summary.update(stage2_seconds=_spread([ts["seconds"] for ts in stages]),
                           switched=sum(ts["switched"] for ts in stages),
                           completed=sum(ts["completed"] for ts in stages),
                           fallbacks=dict(Counter(ts["fallback"] for ts in stages if ts["fallback"])),
                           terminal_positions=sum(ts["terminal_positions"] for ts in stages),
                           policy_fallbacks=sum(ts["policy_fallbacks"] for ts in stages))
        result["variants"].append({"summary": summary, "rows": rows})
        print(json.dumps(summary), flush=True)
    with a.out.open("x") as f:
        json.dump(result, f, indent=1)


if __name__ == "__main__":
    main()

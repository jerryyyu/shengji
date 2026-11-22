"""Compare complete paired S151 generator runs. Run with PYTHONPATH=server."""
import argparse
import json
import math
from pathlib import Path
import sys

from shengji.harvest import trajectory as traj
from shengji.harvest.schema import validate_record


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_times(root, seeds):
    times = {}
    for pair, arm, wall, cpu, inner in read(root / "timings.json"):
        key = pair, arm
        require(type(pair) is int and key not in times, f"invalid or duplicate pair {key}")
        require(all(type(t) in (float, int) and math.isfinite(t) and t > 0
                    for t in (wall, cpu, inner)), f"invalid timing for {key}")
        times[key] = wall, inner
    require(times.keys() == {(i, arm) for i in range(len(seeds)) for arm in "bc"},
            "expected pairs differ from timing rows")
    return times


def read_store(store, seed, args, head, timing):
    wall, inner = timing
    run = read(store / "run.json")
    manifest = read(store / "manifest.json")
    runtime = read(store / "runtime.json")
    config = run["config"]
    clusters = args.rounds // 2
    require(run["identity"]["git_sha"] == head and run["identity"]["git_dirty"] is False
            and config["seed0"] == seed and config["capture_served_budget"] is True
            and not config.get("capture_full_legal_scores")
            and config["run_id"] == run["run_id"]
            and runtime["workers"] == args.workers and runtime["wall_secs"] == inner
            and inner <= wall and runtime["merge"] is False
            and runtime["resume"] is False and runtime["clusters"] == dict(
                requested=clusters, generated=list(range(clusters)), failed=[], reused=[]),
            f"{store}: run identity, budget capture, worker count or completion mismatch")
    sides = {}
    for i in range(clusters):
        side, why = traj.verify_shard(store, config, i, seed + i)
        require(side is not None, f"{store}: cluster {i}: {why}")
        sides[i] = side
    rebuilt = traj.build_run_manifest(config, run["identity"], rounds=args.rounds, sidecars=sides,
                                      merged=None, out_dir=store, seed_window=manifest["seed_window"])
    require(rebuilt == manifest and manifest["counts"]["rounds"] == args.rounds,
            f"{store}: manifest differs from verified shards")
    host = tuple(runtime[k] for k in ("host", "platform", "logical_cpus", "python", "fast_engine", "require_voids"))
    return manifest, (host, run["identity"]["env"])


def comparable_config(manifest):
    config = dict(manifest["config"])
    del config["run_id"]
    env = config["served_runtime"].copy()
    for key in ("SHENGJI_PV_CKPT", "SHENGJI_PV_PRIOR_CKPT", "SHENGJI_PV_UNIFIED_CKPT",
                "SHENGJI_PV_BELIEF_CKPT"):
        require(env[key.replace("CKPT", "SHA256")], f"unbound model path {key}")
        env[key] = Path(env[key]).name
    config["served_runtime"] = env
    return config


def comparable_row(line, run_id):
    row = json.loads(line)
    validate_record(row)
    prefix, sep, ref = row["source_ref"].partition(":")
    require(prefix == run_id and sep and ref, "unexpected source_ref")
    row["source_ref"] = ref
    del row["record_sha256"]
    serving = row["allocation"].get("serving_decision", {})
    for key in ("seconds", "belief_ms", "bury_belief_ms", "exact_lead_seconds"):
        if key in serving:
            serving[key] = None
    belief = (row.get("action_values") or {}).get("belief", {})
    if "belief_ms" in belief:
        belief["belief_ms"] = None
    return row


def compare(args):
    times = read_times(args.root, args.seeds)
    pairs = []
    expected_host = None
    for i, seed in enumerate(args.seeds):
        stores = [args.root / f"{i}-{arm}" / "store" for arm in "bc"]
        runs = [read_store(store, seed, args, head, times[i, arm])
                     for store, head, arm in zip(stores, args.heads, "bc")]
        (a, host_a), (b, host_b) = runs
        if expected_host is None:
            expected_host = host_a
        require(host_a == host_b == expected_host, f"pair {i}: host or engine environment differs")
        require(comparable_config(a) == comparable_config(b), f"pair {i}: config differs")
        require(a["counts"] == b["counts"] and a["work_realized"] == b["work_realized"],
                f"pair {i}: counts or work differ")
        for sa, sb in zip(a["shards"], b["shards"], strict=True):
            with (stores[0] / sa["path"]).open() as left, (stores[1] / sb["path"]).open() as right:
                for x, y in zip(left, right, strict=True):
                    row = comparable_row(x, a["run_id"])
                    require(row == comparable_row(y, b["run_id"]),
                            f"pair {i}: record differs at {row['source_ref']}")
        pairs.append(dict(pair=i, seed=seed, base=times[i, "b"][0], candidate=times[i, "c"][0]))
    totals = {key: sum(pair[key] for pair in pairs) for key in ("base", "candidate")}
    return dict(pairs=pairs, pooled_wall_seconds=totals,
                wall_reduction_percent=100 * (1 - totals["candidate"] / totals["base"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, required=True, help="one seed per timed pair")
    parser.add_argument("--heads", nargs=2, required=True, metavar=("BASE", "CANDIDATE"))
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    args = parser.parse_args()
    if args.rounds < 2 or args.rounds % 2 or args.workers < 1:
        parser.error("expected positive workers and a positive even number of rounds")
    try:
        print(json.dumps(compare(args), indent=2))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        sys.exit(f"comparison refused: {exc}")

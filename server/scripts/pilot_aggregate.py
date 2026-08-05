"""Validate and aggregate paired lead-pilot shards, clustered by deal/state."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys

PRIMARY = ("quota", "random_fill")
ATTRIBUTION = ("full_universe", "mc_more_full_work")
SECONDARY = [
    ("quota", "current"), ("v3", "current"), ("v3", "random_fill"),
    ("random_fill", "current"), ("full_universe", "current"),
    ("mc_more_full_work", "current"),
]
RUN_SCHEMA = "lead-ballot-pilot-v1"
SAMPLER_COUNTERS = ("zero_world_decisions", "rejected_worlds",
                    "impossible_worlds")


class ProtocolError(ValueError):
    pass


def stable_digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def paired(records, a, b, field="regret"):
    """Per-state ``b-a``; positive means arm ``a`` has lower regret."""
    d = [record["arms"][b][field] - record["arms"][a][field]
         for record in records]
    n = len(d)
    if n < 2:
        return (sum(d) / n if n else 0.0), float("inf"), n
    mean = sum(d) / n
    var = sum((value - mean) ** 2 for value in d) / (n - 1)
    return mean, 1.96 * math.sqrt(var / n), n


def _run_problems(data: dict, label: str) -> list[str]:
    problems = []
    records = data.get("records", [])
    required = data.get("required_arms", [])
    report_n = data.get("report_worlds")
    if data.get("schema") != RUN_SCHEMA:
        problems.append(f"{label}: wrong schema")
    if not data.get("complete"):
        problems.append(f"{label}: run is not complete")
    if data.get("tree_dirty"):
        problems.append(f"{label}: dirty tree")
    if data.get("work_violations"):
        problems.append(f"{label}: work-band violations")
    if data.get("replay_errors"):
        problems.append(f"{label}: replay errors")
    if data.get("protocol_failures"):
        problems.append(f"{label}: runner protocol failures")
    if any(data.get("sampler_counter_totals", {}).get(name, 0)
           for name in SAMPLER_COUNTERS):
        problems.append(f"{label}: forbidden sampler counter")
    if not required or len(required) != len(set(required)):
        problems.append(f"{label}: invalid required-arm declaration")
    if len(records) != data.get("n_states"):
        problems.append(f"{label}: {len(records)} records != n_states "
                        f"{data.get('n_states')}")

    seen = set()
    for index, record in enumerate(records):
        where = f"{label}/record-{index}"
        state = record.get("state")
        if state in seen:
            problems.append(f"{where}: duplicate state {state}")
        seen.add(state)
        arms = record.get("arms", {})
        if set(arms) != set(required):
            problems.append(f"{where}: required arms not present exactly once")
            continue
        keys = record.get("report_world_keys")
        if not isinstance(keys, list) or len(keys) != report_n:
            problems.append(f"{where}: report-world identity/count")
            continue
        digest = record.get("report_world_digest")
        if digest != stable_digest(keys):
            problems.append(f"{where}: report-world digest")
        for field in ("reference_returns", "reference_raw_points",
                      "reference_brackets"):
            if len(record.get(field, [])) != report_n:
                problems.append(f"{where}: missing/short {field}")
        stats = record.get("fold_stats", {})
        if set(stats) != {"proposal", "oracle", "report"}:
            problems.append(f"{where}: fold stats missing")
        else:
            for fold, stat in stats.items():
                names = {"requested", "accepted", "attempts", "rejected",
                         "short", "collision_within", "collision_cross"}
                if set(stat) != names or stat["short"] != 0 \
                        or stat["accepted"] != stat["requested"]:
                    problems.append(f"{where}: invalid {fold} fold stats")
        if any(record.get("sampler_counter_deltas", {}).get(name, 0)
               for name in SAMPLER_COUNTERS):
            problems.append(f"{where}: forbidden sampler delta")
        for arm, outcome in arms.items():
            if outcome.get("report_world_digest") != digest:
                problems.append(f"{where}/{arm}: different report worlds")
            if outcome.get("n_report_worlds") != report_n:
                problems.append(f"{where}/{arm}: report count")
            for field in ("arm_returns", "arm_raw_points", "arm_brackets"):
                if len(outcome.get(field, [])) != report_n:
                    problems.append(f"{where}/{arm}: missing/short {field}")
            arm_returns = outcome.get("arm_returns", [])
            reference_returns = record.get("reference_returns", [])
            if len(arm_returns) == report_n and len(reference_returns) == report_n:
                derived = sum(r - a for r, a in zip(reference_returns,
                                                     arm_returns)) / report_n
                if not math.isclose(outcome.get("regret", float("nan")), derived,
                                    rel_tol=1e-12, abs_tol=1e-12):
                    problems.append(f"{where}/{arm}: stored regret != returns")
                arm_mean = sum(arm_returns) / report_n
                if not math.isclose(outcome.get("arm_mean", float("nan")), arm_mean,
                                    rel_tol=1e-12, abs_tol=1e-12):
                    problems.append(f"{where}/{arm}: stored arm mean != returns")
    return problems


def validate_runs(datas: list[dict], labels: list[str] | None = None):
    """Return merged records or raise on any completeness/provenance defect."""
    if not datas:
        raise ProtocolError("no run shards supplied")
    labels = labels or [f"run-{i}" for i in range(len(datas))]
    problems = []
    for data, label in zip(datas, labels):
        problems.extend(_run_problems(data, label))

    # `phase` and `sampler_flags` are cross-shard identity, not decoration:
    # without them a `smoke` shard pools into a DEV verdict, and a shard run
    # under an experimental sampler flag pools with shards that were not —
    # both produce a plausible aggregate over incomparable estimands.
    common_fields = ("schema", "git", "ballot", "experiment_id",
                     "states_sha256", "required_arms", "shard_count",
                     "experiment_n_states", "budget", "work_target", "band",
                     "report_worlds", "oracle_worlds", "full_proposal_worlds",
                     "salt", "phase", "sampler_flags")
    first = datas[0]
    if first.get("phase") != "full":
        problems.append(
            f"phase is {first.get('phase')!r}, not 'full' — a smoke run must "
            f"never aggregate as a DEV result")
    for index, data in enumerate(datas):
        flags = data.get("sampler_flags")
        if flags is None or any(flags.values()):
            problems.append(f"run-{index}: sampler flags {flags} — a scored "
                            f"shard must record all three as false")
    for index, data in enumerate(datas[1:], 1):
        for field in common_fields:
            if data.get(field) != first.get(field):
                problems.append(f"run-{index}: mixed {field}")
    shard_count = first.get("shard_count")
    indices = [data.get("shard_index") for data in datas]
    if not isinstance(shard_count, int) or shard_count <= 0:
        problems.append("invalid shard count")
    elif sorted(indices) != list(range(shard_count)):
        problems.append(f"shards {sorted(indices)} != required "
                        f"{list(range(shard_count))}")

    records = [record for data in datas for record in data.get("records", [])]
    states = [record.get("state") for record in records]
    deals = [record.get("deal_seed") for record in records]
    if len(states) != len(set(states)):
        problems.append("duplicate state across shards")
    if len(deals) != len(set(deals)):
        problems.append("more than one state from a deal")
    if len(records) != first.get("experiment_n_states"):
        problems.append(f"merged {len(records)} records != experiment_n_states "
                        f"{first.get('experiment_n_states')}")
    if not records:
        problems.append("no records")
    if problems:
        raise ProtocolError("; ".join(problems))
    return records, first


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()
    datas = [json.load(open(path)) for path in args.runs]
    try:
        records, manifest = validate_runs(datas, args.runs)
    except ProtocolError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)

    print(f"run {manifest['git']}  states {len(records)}  "
          f"ballot {manifest['ballot']}")
    print(f"work target {manifest['work_target']} +/- "
          f"{manifest['band']*100:.0f}%\n")
    print(f"{'contrast':34} {'diff':>9} {'95% CI':>10}  n   verdict")
    for label, (arm, control) in (("PRIMARY", PRIMARY),
                                  ("ATTRIB ", ATTRIBUTION)):
        mean, half, n = paired(records, arm, control)
        verdict = (f"FAVOURS {arm}" if mean - half > 0 else
                   f"FAVOURS {control}" if mean + half < 0 else "INCLUDES 0")
        print(f"{label + ' ' + arm + ' - ' + control:34} {mean:+9.3f} "
              f"{half:10.3f} {n:3d}  {verdict}")
    for arm, control in SECONDARY:
        mean, half, n = paired(records, arm, control)
        verdict = (f"favours {arm}" if mean - half > 0 else
                   f"favours {control}" if mean + half < 0 else "includes 0")
        print(f"{'  ' + arm + ' - ' + control:34} {mean:+9.3f} "
              f"{half:10.3f} {n:3d}  {verdict}")

    print(f"\n{'arm':24} {'mean regret':>12} {'oracle match':>13} "
          f"{'mean work':>10}")
    for arm in manifest["required_arms"]:
        regrets = [record["arms"][arm]["regret"] for record in records]
        matches = [record["arms"][arm]["matched_oracle"] for record in records]
        work = [record["arms"][arm]["work"] for record in records]
        print(f"{arm:24} {sum(regrets)/len(regrets):12.3f} "
              f"{100*sum(matches)/len(matches):12.1f}% "
              f"{sum(work)/len(work):10.0f}")
    print("\nOne state/deal is one cluster. Worlds are paired Monte Carlo draws, "
          "not independent experiment observations.")


if __name__ == "__main__":
    main()

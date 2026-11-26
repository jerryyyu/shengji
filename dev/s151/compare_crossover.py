"""Read the proposed 26-worker S151 generator crossover. Run with PYTHONPATH=server."""
import argparse
from collections import Counter
from contextlib import ExitStack
from itertools import zip_longest
import json
import math
from pathlib import Path
import sys

from compare_generator import comparable_config, normalize_row, read, read_store, read_times, require

SEEDS = (4301400, 4301504, 4301608, 4301712)
HEADS = ("4112920934d8aa4f2e4f1df650c8199edda1bdbd",) * 2


RELEASE_BOT = 'pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-reac0a771-bury-hybrid-bwv-bbw-e191a6461fa8-sc8-usharee2951d35-uvaluee2951d35-ureplye2951d35-ufast'
SERVING_PINS = {
    "SHENGJI_Y_CAPTURE_FLY_SHA256": "ce87b179953231c812bf9de14d612d7566e12c4504463e1e297226949f774e9b",
    "SHENGJI_Y_CAPTURE_RUNNER_SHA256": "51e4331c24f88765dee308b81e1e08f0deb00a1e415ae8d305c6a4c73cd8ca37",
    "SHENGJI_PV_SHA256": "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd",
    "SHENGJI_PV_PRIOR_SHA256": "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf",
    "SHENGJI_PV_UNIFIED_SHA256": "e2951d35eeabd167347c3b5608a8065dffb9bd304b51aa4759eabbba1ce05883",
    "SHENGJI_PV_BELIEF_SHA256": "35e225cf3afd460d231a44192e60be8595a5d7fce81c860f0bfe3153506f66e3",
}


def require_served_workload(runtime, config):
    require(runtime["fast_engine"] is True, "compiled engine required")
    require(config["policy"] == RELEASE_BOT,
            "unexpected release policy")
    require(config["served_budgets"] == dict(play_seconds=3, bury_seconds=3, wall_clock_dependent=True),
            "resolved budget mismatch")
    env = config["served_runtime"]
    require(all(env.get(k) == v for k, v in SERVING_PINS.items()), "serving identity mismatch")
    require(all(float(env[k]) == 3 for k in ("SHENGJI_PV_SERVING_BUDGET_SECONDS",
                                             "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS")), "configured budget mismatch")


def validate_arm(arm, command, runtime, *, workers=26, clusters=104):
    split = arm == "c"
    require(arm in ("b", "c") and isinstance(command, list)
            and command.count("--split-tail-mirrors") == int(split)
            and runtime.get("split_tail_mirrors", False) is split, "scheduler mode mismatch")
    tasks = runtime["per_cluster"]
    require(runtime["workers"] == workers and set(tasks) == {str(i) for i in range(clusters)},
            "scheduler workload mismatch")
    expected = {str(i) for i in range(max(0, clusters - workers), clusters)} if split else set()
    actual = {k for k, v in tasks.items() if "worker_wall_secs" in v}
    require(actual == expected, "split cluster set mismatch")
    for k in actual:
        seconds = tasks[k]["worker_wall_secs"]
        require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
                "invalid split worker duration")


def percent(a, b):
    return 200 * (a - b) / (a + b)


def block_order(block):
    first = 2 * block
    arms = "bccb" if block % 2 == 0 else "cbbc"
    return [(first + i // 2, arm) for i, arm in enumerate(arms)]


def cluster_interval(store, clusters):
    tasks = read(store / "runtime.json")["per_cluster"]
    require(set(tasks) == {str(i) for i in range(clusters)}, f"{store}: missing cluster intervals")
    intervals = [(v["started_at"], v["finished_at"]) for v in tasks.values()]
    require(all(math.isfinite(a) and math.isfinite(b) and 0 < a < b for a, b in intervals),
            f"{store}: invalid cluster timestamps")
    return min(a for a, _ in intervals), max(b for _, b in intervals)


def count_play_time(counts, row, budget):
    if row["decision_kind"] != "play":
        return
    rec = row["allocation"].get("serving_decision") or {}
    key = "elapsed_seconds" if rec.get("schema") == "pv-search-fallback-v1" else "seconds"
    elapsed = rec.get(key)
    if elapsed is None:
        counts["missing"] += 1
        return "missing"
    require(type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= 0,
            "invalid play duration")
    counts["timed"] += 1
    counts["at_or_over_budget"] += elapsed >= budget
    return "at_or_over_budget" if elapsed >= budget else "within_budget"


def read_block(root, seed, order, times, args, previous_end, configuration):
    stores = []
    manifests = []
    for i, arm in order:
        store = root / f"{i}-{arm}" / "store"
        manifest, host = read_store(store, seed, args, HEADS["bc".index(arm)], times[i, arm])
        require(host[0][0] == args.host, f"{store}: expected host {args.host}")
        start, end = cluster_interval(store, args.rounds // 2)
        require(start >= previous_end, f"{store}: cluster execution overlaps or is out of order")
        previous_end = end
        config = comparable_config(manifest)
        del config["seed0"]
        if configuration is None:
            configuration = host, config
        require((host, config) == configuration, f"{store}: configuration or host drift")
        stores.append(store)
        manifests.append(manifest)

    first_difference = None
    first_budget_difference = None
    work_keys = ("counts", "work_realized")
    work_matches = all(all(m[k] == manifests[0][k] for k in work_keys) for m in manifests)
    events = [Counter() for _ in stores]
    play_times = [Counter(timed=0, at_or_over_budget=0, missing=0) for _ in stores]
    budgets = [float(m["config"]["served_runtime"]["SHENGJI_PV_SERVING_BUDGET_SECONDS"]) for m in manifests]
    require(all(math.isfinite(b) and b > 0 for b in budgets), "invalid served play budget")
    for shards in zip(*(m["shards"] for m in manifests), strict=True):
        with ExitStack() as stack:
            files = [stack.enter_context((p / shard["path"]).open()) for p, shard in zip(stores, shards)]
            for lines in zip_longest(*files):
                rows = []
                budget_states = []
                for j, line in enumerate(lines):
                    row = json.loads(line) if line is not None else None
                    state = count_play_time(play_times[j], row, budgets[j]) if row is not None else None
                    budget_states.append(state)
                    if row is not None:
                        row = normalize_row(row, manifests[j]["run_id"])
                        rec = row["allocation"].get("serving_decision") or {}
                        if row["decision_kind"] == "play" and rec.get("schema") == "pv-search-fallback-v1":
                            # The budget classification above retains a clock crossing even when the move agrees.
                            rec.pop("elapsed_seconds", None)
                    rows.append(row)
                    if row is None:
                        continue
                    rec = row["allocation"].get("serving_decision") or {}
                    events[j]["greedy_deadline_fired"] += bool(rec.get("leaf_greedy_deadline_fired"))
                    if rec.get("exact_follow_abandoned"):
                        events[j][f"exact_follow_abandoned:{rec['exact_follow_abandoned']}"] += 1
                    if rec.get("exact_lead_status"):
                        events[j][f"exact_lead:{rec['exact_lead_status']}"] += 1
                if first_budget_difference is None and any(s != budget_states[0] for s in budget_states):
                    first_budget_difference = {
                        p.parent.name: {"state": state, "source_ref": r["source_ref"] if r else None}
                        for p, state, r in zip(stores, budget_states, rows)}
                if first_difference is None:
                    for j, row in enumerate(rows[1:], 1):
                        if row != rows[0]:
                            first_difference = dict(reference=stores[0].parent.name,
                                                    compared=stores[j].parent.name,
                                                    source_refs=[r["source_ref"] if r else None
                                                                 for r in (rows[0], row)])
                            break
    for manifest, event in zip(manifests, events):
        event.update({k: v for k, v in manifest["counts"].items() if "fallback" in k or k == "incomplete_work"})
    pairs = [dict(base=times[i, "b"][0], candidate=times[i, "c"][0]) for i in sorted({i for i, _ in order})]
    base, candidate = ([pair[k] for pair in pairs] for k in ("base", "candidate"))
    for pair in pairs:
        pair["reduction_percent"] = percent(pair["base"], pair["candidate"])
    block = dict(seed=seed, pairs=pairs, base=sum(base), candidate=sum(candidate),
                 reduction_percent=percent(sum(base), sum(candidate)),
                 repeat_difference_percent=dict(base=abs(percent(*base)), candidate=abs(percent(*candidate))),
                 work_matches=work_matches, first_record_difference=first_difference,
                 first_budget_difference=first_budget_difference,
                 play_compute_by_invocation={p.parent.name: dict(t) for p, t in zip(stores, play_times)},
                 events_by_invocation={p.parent.name: dict(e) for p, e in zip(stores, events)})
    if work_matches and first_difference is None:
        block["events_per_invocation"] = dict(events[0])
    return block, previous_end, configuration


def verdict(blocks):
    base = sum(b["base"] for b in blocks)
    candidate = sum(b["candidate"] for b in blocks)
    gain = percent(base, candidate)
    noise = max(max(b["repeat_difference_percent"].values()) for b in blocks)
    matched = all(b["work_matches"] and b["first_record_difference"] is None for b in blocks)
    budgets_match = all(b["first_budget_difference"] is None and
                        all(t["missing"] == 0 for t in b["play_compute_by_invocation"].values())
                        for b in blocks)
    passed = matched and budgets_match and all(b["candidate"] < b["base"] for b in blocks) and gain > noise
    return dict(blocks=blocks, pooled_seconds=dict(base=base, candidate=candidate),
                pooled_symmetric_reduction_percent=gain, largest_repeat_difference_percent=noise,
                complete_matching_play_budget_evidence=budgets_match, matched_work_and_decisions=matched, observed_noise_gate="PASS" if passed else "INCONCLUSIVE")


def compare(root):
    args = argparse.Namespace(rounds=208, workers=26, host="Jerrys-Mac-Studio.local")
    times = read_times(root, [s for s in SEEDS for _ in range(2)])
    orders = [block_order(i) for i in range(len(SEEDS))]
    require(list(times) == [key for order in orders for key in order], "timing sequence differs from crossover plan")
    for index, ((pair, arm), durations) in enumerate(times.items()):
        path = root / f"{pair}-{arm}" / "capture.json"
        receipt = read(path)
        runtime = read(path.parent / "store/runtime.json")
        validate_arm(arm, receipt["command"], runtime)
        require_served_workload(runtime, read(path.parent / "store/run.json")["config"])
        timing = receipt["timing"]
        require(receipt["index"] == index and receipt["head"] == HEADS["bc".index(arm)]
                and len(timing) == 5 and timing[:2] == [pair, arm]
                and (timing[2], timing[4]) == durations,
                f"{path}: invocation or wall time differs from assembled timings")
    blocks = []
    previous_end, configuration = 0, None
    for seed, order in zip(SEEDS, orders, strict=True):
        block, previous_end, configuration = read_block(root, seed, order, times, args, previous_end, configuration)
        blocks.append(block)
    return verdict(blocks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    try:
        report = compare(parser.parse_args().root)
        print(json.dumps(report, indent=2))
        if not report["complete_matching_play_budget_evidence"]:
            sys.exit("comparison inconclusive: play clock missing or budget crossing differed")
        if not report["matched_work_and_decisions"]:
            sys.exit("comparison inconclusive: gameplay or work differed")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        sys.exit(f"comparison refused: {exc}")

"""Decide the M2 serving-cost gate from the complete paired Fly timing capture."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

from timing import (
    A_BELIEF_SHA,
    A_NAME,
    A_UNIFIED_SHA,
    APP,
    B_BELIEF_SHA,
    B_NAME,
    B_UNIFIED_SHA,
    CAP_SECONDS,
    MEM_FLOOR_KB,
    SEEDS,
)


SIDES = {
    "A": (A_NAME, A_UNIFIED_SHA, A_BELIEF_SHA),
    "B": (B_NAME, B_UNIFIED_SHA, B_BELIEF_SHA),
}
PLAY_SCHEMA = "pv-search-decision-v1"
PLAY_FALLBACK_SCHEMA = "pv-search-fallback-v1"
MIN_PLAYS = 300
MAX_LATENCY_RATIO = 1.10
MAX_SERVER_KIB = 1536 * 1024


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def measure(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"invalid measurement: {label}")
    return value


def memory(value, label):
    require(type(value) is int and value > 0, f"missing memory measurement: {label}")
    return value


def regular_bytes(directory, filename):
    path = directory / filename
    require(path.is_file() and not path.is_symlink(), f"missing regular capture file: {filename}")
    return path.read_bytes()


def load_capture(directory, seal_sha256):
    require(directory.is_dir() and not directory.is_symlink(), "missing regular capture directory")
    seal = regular_bytes(directory, "SHA256SUMS")
    require(hashlib.sha256(seal).hexdigest() == seal_sha256, "capture seal SHA-256 mismatch")
    filenames = ("decisions.jsonl", "events.jsonl", "samples.jsonl")
    require(seal.endswith(b"\n"), "incomplete seal")
    lines = seal.decode("ascii").splitlines()
    require(len(lines) == len(filenames), "wrong sealed capture file count")
    verified = {}
    for filename, line in zip(filenames, lines):
        match = re.fullmatch(r"([0-9a-f]{64})  " + re.escape(filename), line)
        require(match is not None, f"invalid seal entry for {filename}")
        payload = regular_bytes(directory, filename)
        require(hashlib.sha256(payload).hexdigest() == match[1], f"capture bytes differ: {filename}")
        verified[filename] = payload

    capture = {}
    for filename, payload in verified.items():
        require(payload.endswith(b"\n"), f"incomplete JSONL row: {filename}")
        rows = [json.loads(line) for line in payload.splitlines()]
        require(all(isinstance(row, dict) for row in rows), f"invalid JSONL row: {filename}")
        capture[filename] = rows
    return capture


def check_events(events, decisions):
    require(events and events[-1]["kind"] == "terminal", "missing successful terminal")
    expected = ["preflight", "names", "identity", "identity"]
    expected += ["round_start", "round_end"] * len(SEEDS)
    expected.append("terminal")
    require([event["kind"] for event in events] == expected,
            "unexpected event sequence, duplicate terminal or abort")
    preflight, names, a_ident, b_ident = events[:4]
    require(all(names[side] == identity[0] for side, identity in SIDES.items()),
            "wrong bot names")
    for side, ident in zip(SIDES, (a_ident, b_ident)):
        name, unified, belief = SIDES[side]
        require((ident["side"], ident["env_bot"], ident["policy"], ident["unified_sha256"],
                 ident["belief_sha256"], ident["tree"]) == (side, name, name, unified, belief, str(APP)),
                f"wrong serving identity for {side}")
        require(all(ident[key] is True for key in ("fast", "have_native", "compiled_decompose")),
                f"missing compiled serving path for {side}")

    terminal = events[-1]
    require(terminal["status"] == "DONE" and not terminal.get("reason")
            and measure(terminal["elapsed"], "elapsed") <= CAP_SECONDS
            and type(terminal["decisions"]) is int and terminal["decisions"] == len(decisions),
            "terminal did not complete the full timing capture")
    health = terminal["healthz_end"]
    activity = health["activity"]
    baseline = preflight["baseline"]
    require(health["ok"] is True and health["bot"] == A_NAME and health["rooms"] == 0
            and baseline == [0, 0, 0] and activity["rooms_created"] == activity["games_started"] == 0,
            "serving identity or isolation changed")

    offset = 0
    for i, seed in enumerate(SEEDS):
        start, end = events[4 + 2 * i:6 + 2 * i]
        require(start["seed"] == end["seed"] == seed and end["phase"] == "round_end",
                f"round {seed} did not reach round_end")
        limit = end["decisions"]
        require(type(limit) is int and offset + 1 < limit <= len(decisions),
                f"missing decisions for round {seed}")
        group = decisions[offset:limit]
        require(all(row["seed"] == seed for row in group)
                and group[0]["phase"] == "bury" and all(row["phase"] == "play" for row in group[1:]),
                f"incomplete paired round {seed}")
        offset = limit
    require(offset == len(decisions), "extra decisions beyond the completed rounds")
    return terminal


def check_decisions(decisions):
    for index, row in enumerate(decisions):
        first = "A" if index % 2 == 0 else "B"
        require(type(row["index"]) is int and row["index"] == index and row["first"] == first,
                f"missing or out-of-order paired decision {index}")
        for side, (name, _, _) in SIDES.items():
            arm = row[side]
            require(arm["policy"] == name, f"policy drift in paired decision {index} {side}")
            copied, decided, total = (measure(arm[key], f"{index}/{side}/{key}")
                                      for key in ("copy_s", "decide_s", "total_s"))
            require(total > 0 and math.isclose(total, copied + decided, abs_tol=1e-9),
                    f"invalid wall timing in paired decision {index} {side}")
            require(type(arm["fallback"]) is bool, f"missing fallback flag in {index} {side}")
            belief_fallback = arm["belief_fallback_any"]
            counted = type(belief_fallback) is int and belief_fallback in (0, 1)
            if row["phase"] == "play":
                expected_schema = PLAY_FALLBACK_SCHEMA if arm["fallback"] else PLAY_SCHEMA
                require(arm.get("schema") == expected_schema,
                        f"play schema and fallback flag disagree in {index} {side}")
                # WHL and belief worlds tally every draw in completed play searches.
                require(counted or (arm["fallback"] and belief_fallback is None),
                        f"missing or invalid play belief fallback tally in {index} {side}")
            else:
                require(counted or belief_fallback is None,
                        f"invalid bury belief fallback flag in {index} {side}")
        if row["phase"] == "play":
            require((row["B"]["unified"] or {}).get("shared") == 1,
                    f"challenger did not use shared unified serving in play {index}")


def check_memory(samples, decisions, terminal):
    require(len(samples) >= 2 and samples[0]["tag"] == "before" and samples[-1]["tag"] == "after",
            "missing before/after memory samples")
    require(all(sample["tag"] == "watch" for sample in samples[1:-1]),
            "unexpected memory-sample sequence")
    available = min(memory(sample["mem_available_kb"], "available") for sample in samples)
    require(available >= MEM_FLOOR_KB, "memory watchdog floor breached")
    server = max(memory(sample["server"]["VmHWM"], "server HWM") for sample in samples)
    worker = {}
    for side in SIDES:
        final = terminal["worker_final"][side]
        worker[side] = max(
            memory(final["status"]["VmHWM"], f"{side} final HWM"),
            *(memory(row[side]["status"]["VmHWM"], f"{side} HWM") for row in decisions),
        )
    # The reference server is idle, so the full B worker peak bounds the extra serving memory.
    projected = server + worker["B"]
    return {
        "server_hwm_mib": server / 1024,
        "worker_hwm_mib": {side: value / 1024 for side, value in worker.items()},
        "projected_server_mib": projected / 1024,
        "min_available_mib": available / 1024,
    }


def decide(directory, seal_sha256):
    capture = load_capture(directory, seal_sha256)
    events, decisions, samples = (capture[name] for name in ("events.jsonl", "decisions.jsonl", "samples.jsonl"))
    terminal = check_events(events, decisions)
    check_decisions(decisions)
    memory_stats = check_memory(samples, decisions, terminal)

    plays = [row for row in decisions if row["phase"] == "play"]
    require(len(plays) >= MIN_PLAYS, f"need at least {MIN_PLAYS} paired plays")
    means = {side: statistics.fmean(row[side]["total_s"] for row in plays) for side in SIDES}
    ratio = means["B"] / means["A"]
    require(math.isfinite(ratio), "invalid wall latency ratio")
    fallbacks = {
        side: {
            "play": sum(row[side]["fallback"] for row in plays),
            "belief": sum(bool(row[side]["belief_fallback_any"]) for row in plays),
        }
        for side in SIDES
    }
    gates = {
        "latency": ratio <= MAX_LATENCY_RATIO,
        "play_fallbacks": fallbacks["B"]["play"] <= fallbacks["A"]["play"],
        "belief_fallbacks": fallbacks["B"]["belief"] <= fallbacks["A"]["belief"],
        "memory": memory_stats["projected_server_mib"] <= MAX_SERVER_KIB / 1024,
    }
    return {
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "seal_sha256": seal_sha256,
        "sides": {side: {"policy": identity[0], "unified_sha256": identity[1], "belief_sha256": identity[2]}
                  for side, identity in SIDES.items()},
        "seeds": list(SEEDS),
        "paired_plays": len(plays),
        "wall_mean_seconds": means,
        "wall_ratio_B_over_A": ratio,
        "fallbacks": fallbacks,
        "memory": memory_stats,
        "gates": gates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outdir", type=Path, help="sealed timing output directory")
    parser.add_argument("--seal-sha256", required=True, help="independently published SHA256SUMS digest")
    args = parser.parse_args(argv)
    try:
        result = decide(args.outdir, args.seal_sha256)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        print(json.dumps({"verdict": "INSUFFICIENT", "reason": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["verdict"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())

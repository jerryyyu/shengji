"""Freeze the bounded DEV diagnostic behind S0's margin decision.

This is calibration evidence, never a promotion set.  It scans the first 150
states in the already-inspected DEV-512 order with a named selection RNG per
state, records every incumbent N=30 decision, then takes the first 20 actual
non-candidate-0 overrides and evaluates that frozen pair on 300 fresh paired
worlds.  The artifact carries every paired delta, so the reported sign rate,
effect size and candidate report-dose grid can be re-derived without rerunning
rollouts or trusting prose.

Run only from a clean tree:

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
      scripts/s0_override_audit.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pilot_states as PS  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402


SCHEMA = "s0-override-audit-v1"
STATE_ASSET = "rl_data/pilot_dev512.v6.json"
STATE_LIMIT = 150
DETAIL_LIMIT = 20
REPORT_WORLDS = 300
DOSE_GRID = (30, 60, 120, 300)
SALT = "s0-override-audit-v1"
DEFAULT_OUT = "tests/data/s0_override_audit.v1.json"


def digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def named_seed(state_key: str, purpose: str) -> int:
    raw = hashlib.sha256(f"{SALT}|{state_key}|{purpose}".encode()).digest()
    return int.from_bytes(raw[:8], "big")


def state_key(st: dict) -> str:
    return f"{st['source']}:{st['seed']}:{st['ply']}:{st['seat']}"


def load_rows(states: list[dict]) -> dict:
    wanted = {}
    for st in states:
        wanted.setdefault(st["source"], set()).add((st["seed"], st["ply"]))
    paths = {name: corpus for name, corpus, _split in PS.SOURCES}
    rows = {}
    for source, keys in wanted.items():
        with open(paths[source]) as fh:
            for line in fh:
                row = json.loads(line)
                key = (row["seed"], row["ply"])
                if key in keys:
                    rows[(source, *key)] = row
    missing = [(st["source"], st["seed"], st["ply"]) for st in states
               if (st["source"], st["seed"], st["ply"]) not in rows]
    if missing:
        raise RuntimeError(f"missing {len(missing)} source rows: {missing[:3]}")
    return rows


def prefix_stats(deltas: list[float], n: int, critical: float = 1.70) -> dict:
    values = deltas[:n]
    mean = statistics.fmean(values)
    if n < 2:
        se = math.inf
    else:
        se = statistics.stdev(values) / math.sqrt(n)
    return {"n": n, "gap": mean, "se": se,
            "lcb": mean - critical * se,
            "mean_gt_0": mean > 0,
            "lcb_gt_0": mean - critical * se > 0,
            "lcb_gt_5": mean - critical * se > 5}


def choose_report_dose(detailed: list[dict]) -> dict:
    """Predeclared calibration rule; 300-world signs are DEV references only.

    Pick the smallest dose that (a) agrees in sign with the 300-world mean on
    at least 80% of these frozen overrides, (b) confidently retains at least
    half of the 300-world-positive overrides, and (c) confidently retains none
    of the 300-world-negative overrides. If no dose clears, use 300 and mark
    the rule unsatisfied; the S0a full-game screen still decides strength.
    """
    positive = [i for i, row in enumerate(detailed)
                if row["report"]["gap"] > 0]
    negative = [i for i, row in enumerate(detailed)
                if row["report"]["gap"] <= 0]
    required_retained = math.ceil(len(positive) / 2)
    diagnostics = []
    selected = None
    for grid_index, n in enumerate(DOSE_GRID):
        stats = [row["dose_grid"][grid_index] for row in detailed]
        sign_agree = sum((s["gap"] > 0) == (row["report"]["gap"] > 0)
                         for s, row in zip(stats, detailed))
        retained = sum(stats[i]["lcb_gt_0"] for i in positive)
        false_supported = sum(stats[i]["lcb_gt_0"] for i in negative)
        clears = (sign_agree / len(detailed) >= 0.80
                  and retained >= required_retained
                  and false_supported == 0)
        diagnostics.append({
            "n": n, "sign_agreement": sign_agree,
            "positive_reference": len(positive),
            "positive_retained_lcb0": retained,
            "negative_reference": len(negative),
            "negative_supported_lcb0": false_supported,
            "clears": clears,
        })
        if clears and selected is None:
            selected = n
    return {"selected": selected or DOSE_GRID[-1],
            "rule_satisfied": selected is not None,
            "diagnostics": diagnostics}


def preflight(out: str, allow_dirty: bool) -> tuple[str, bool]:
    if os.environ.get("SHENGJI_FAST") != "1":
        raise RuntimeError("set SHENGJI_FAST=1")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise RuntimeError("set SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise RuntimeError("compiled engine requested but not active")
    if os.path.exists(out):
        raise RuntimeError(f"refusing to overwrite immutable artifact {out}")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], check=True,
                                capture_output=True, text=True).stdout.strip())
    if dirty and not allow_dirty:
        raise RuntimeError("refusing a frozen artifact from a dirty tree")
    return sha, dirty


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--allow-dirty", action="store_true",
                    help="diagnostic only; a dirty artifact cannot close S0")
    args = ap.parse_args()
    sha, dirty = preflight(args.out, args.allow_dirty)

    state_asset = json.load(open(STATE_ASSET))
    states = state_asset["states"][:STATE_LIMIT]
    if len(states) != STATE_LIMIT:
        raise RuntimeError(f"state asset has only {len(states)} requested states")
    rows = load_rows(states)

    decisions = []
    detailed = []
    identity = None
    for index, st in enumerate(states):
        key = state_key(st)
        rnd = PS.replay(rows[(st["source"], st["seed"], st["ply"])])
        seat = st["seat"]
        seed = named_seed(key, "selection-n30")
        bot = make_bot("mc-strong", seed=seed)
        played = bot.decide_play(rnd, seat)
        rec = bot.last_decision_record
        row = {"index": index, "state_key": key, "source": st["source"],
               "deal_seed": st["seed"], "ply": st["ply"], "seat": seat,
               "role": "attacker" if rnd.is_attacker(seat) else "defender",
               "selection_seed": seed, "played": list(played),
               "searched": rec is not None}
        if rec is not None:
            row.update({"candidate0": rec["candidates"][0],
                        "played_index": rec["played_index"],
                        "raw_winner_index": rec["raw_winner_index"],
                        "reason": rec["reason"],
                        "selection_complete": rec["work"]["complete"]})
            identity = identity or {"code": rec["code"],
                                    "ballot": rec["ballot"]}
        decisions.append(row)

        if (rec is None or rec["played_index"] == 0
                or len(detailed) >= DETAIL_LIMIT):
            continue
        challenger = rec["played_index"]
        report_seed = named_seed(key, "report-n300")
        report_bot = make_bot("mc-strong", seed=0)
        mem = Memory(rnd, seat,
                     own_kitty=getattr(report_bot, "BANKER_KITTY", True))
        report = report_bot._report_fold_gap(
            rnd, seat, mem, rnd.is_attacker(seat),
            rec["candidates"][challenger], rec["candidates"][0],
            REPORT_WORLDS, seed=report_seed, keep_deltas=True)
        if not report["complete"]:
            raise RuntimeError(f"short report fold for {key}: {report}")
        deltas = report.pop("deltas")
        detailed.append({
            "state_key": key, "selection_seed": seed,
            "report_seed": report_seed, "role": row["role"],
            "candidate0": rec["candidates"][0],
            "challenger": rec["candidates"][challenger],
            "selection_gap": (rec["means"][challenger] - rec["means"][0]),
            "report": report, "paired_deltas": deltas,
            "dose_grid": [prefix_stats(deltas, n) for n in DOSE_GRID],
        })

    if len(detailed) != DETAIL_LIMIT:
        raise RuntimeError(f"found only {len(detailed)} overrides; expected "
                           f"the frozen first {DETAIL_LIMIT}")
    if any(not d.get("selection_complete", True) for d in decisions):
        raise RuntimeError("a selection decision did not consume N=30")

    gaps = [d["report"]["gap"] for d in detailed]
    dose_choice = choose_report_dose(detailed)
    summary = {
        "states": len(decisions),
        "searched": sum(d["searched"] for d in decisions),
        "current_overrides": sum(d.get("played_index", 0) != 0
                                 for d in decisions),
        "detailed_overrides": len(detailed),
        "positive_report_gap": sum(g > 0 for g in gaps),
        "mean_report_gap": statistics.fmean(gaps),
        "median_abs_report_gap": statistics.median(abs(g) for g in gaps),
        "selected_report_worlds": dose_choice["selected"],
        "dose_rule_satisfied": dose_choice["rule_satisfied"],
        "dose_grid": {
            str(n): {
                "mean_gt_0": sum(x["dose_grid"][i]["mean_gt_0"]
                                 for x in detailed),
                "lcb_gt_0": sum(x["dose_grid"][i]["lcb_gt_0"]
                                for x in detailed),
                "lcb_gt_5": sum(x["dose_grid"][i]["lcb_gt_5"]
                                for x in detailed),
            } for i, n in enumerate(DOSE_GRID)
        },
    }
    payload = {
        "schema": SCHEMA, "created": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "git_sha": sha, "tree_dirty": dirty,
        "script_sha256": digest(__file__),
        "state_asset": STATE_ASSET,
        "state_asset_sha256": digest(STATE_ASSET),
        "selection_rule": "first 150 DEV-512 states in frozen artifact order; "
                          "first 20 actual mc-strong N=30 overrides",
        "state_limit": STATE_LIMIT, "detail_limit": DETAIL_LIMIT,
        "report_worlds": REPORT_WORLDS, "dose_grid": list(DOSE_GRID),
        "salt": SALT, "identity": identity,
        "source_assets": state_asset.get("sources", {}),
        "dose_selection": dose_choice,
        "summary": summary, "decisions": decisions, "overrides": detailed,
    }
    tmp = args.out + ".tmp"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "x") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    os.replace(tmp, args.out)
    print(json.dumps(summary, indent=2))
    print(f"artifact: {args.out}\nsha256: {digest(args.out)}")


if __name__ == "__main__":
    main()

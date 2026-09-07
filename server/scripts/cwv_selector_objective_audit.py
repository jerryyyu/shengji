#!/usr/bin/env python3
"""FIT-only points versus level utility in the unchanged MC-LCB consumer.

No new inference or games. Reuse frozen finished-trick shortlists and independent
1024-world reference matrices. Calculate common N30/R300 rollout matrices once
per root; replay both objectives through production's actual decide_play.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from shengji.ai.cwv_policy import sample_worlds
from shengji.ai.mcbot import _child_seed
from shengji.ai.registry import make_bot
from shengji.luna.game import _round_from_snapshot
from shengji.train.cwv_horizon_audit import reference_returns
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def verify_control(saved, replayed):
    """Saved actual rollout consumer is the control, not a duplicate selector."""
    if saved is None or replayed is None:
        if saved is not replayed:
            raise ValueError("control search/no-search mismatch")
        return
    for key in ("candidates", "played", "played_index", "reason", "report_candidate_index",
                "raw_winner_index", "n_by_candidate", "worlds", "work", "report_seed"):
        if saved[key] != replayed[key]:
            raise ValueError(f"control consumer mismatch: {key}")
    for key in ("means", "paired_se"):
        if not np.allclose(saved[key], replayed[key], rtol=0, atol=1e-12):
            raise ValueError(f"control consumer mismatch: {key}")
    for key in ("gap", "se", "statistic", "critical", "min_gain"):
        if abs(saved["report_fold"][key] - replayed["report_fold"][key]) > 1e-12:
            raise ValueError(f"control report mismatch: {key}")


def run_case(entry, saved, reference, config):
    from shengji.train.cwv_selector_objective_audit import replay_selector

    start = time.perf_counter()
    if entry.get("provenance", {}).get("split") != "fit":
        raise ValueError("objective diagnostic accepts only FIT positions")
    if saved["state_id"] != entry["id"] or reference["state_id"] != entry["id"]:
        raise ValueError("objective root identity mismatch")
    if (reference["binding"]["entry_hash"] != digest(entry) or
            reference["binding"]["source_hashes"][1] != digest(saved)):
        raise ValueError("independent reference source mismatch")
    arms = {name: value for name, value in saved["arms"].items() if name.endswith("/finished")}
    if not arms:
        raise ValueError("no frozen finished-trick arms")
    actions = sorted({tuple(sorted(saved["actions"][i])) for arm in arms.values()
                      for i in arm["shortlist_indices"]})
    lookup = {action: i for i, action in enumerate(actions)}
    rnd = _round_from_snapshot(entry["snapshot"])
    seed = int(entry["id"][:15], 16) ^ config["seed"]
    initial = make_bot("mc-s0-report-lcb", seed=seed)
    folds = {}
    fresh_rollouts = 0
    for name, child_seed, n in (("selection", seed, config["selection_worlds"]),
                               ("report", _child_seed(initial.rng.getstate(), "s0-report"), config["report_worlds"])):
        worlds, attempts = sample_worlds(make_bot("mc-s0-report-lcb", seed=child_seed), rnd, rnd.turn, n)
        if len(worlds) != n:
            raise ValueError("objective world population underfilled")
        values = reference_returns(rnd, rnd.turn, [list(a) for a in actions], worlds)
        folds[name] = {"points": values["points"], "worlds_sha256": digest(worlds),
                       "attempts": attempts, "seed": child_seed}
        fresh_rollouts += n * len(actions)
    reference_index = {tuple(a): i for i, a in enumerate(reference["actions"])}
    values = np.asarray(reference["returns"]["levels"], dtype=float)
    if values.shape != (1024, len(reference_index)):
        raise ValueError("reference matrix shape mismatch")
    means = values.mean(0)
    base = tuple(sorted(saved["incumbent"]))
    reference_base = means[reference_index[base]]
    outputs = {}
    for model, arm in arms.items():
        ballot = [list(saved["actions"][i]) for i in arm["shortlist_indices"]]
        offsets = [lookup[tuple(sorted(a))] for a in ballot]
        for objective in ("points", "levels"):
            replay = replay_selector(rnd, rnd.turn, ballot, folds["selection"]["points"][:, offsets],
                                     folds["report"]["points"][:, offsets], seed=seed, objective=objective)
            if objective == "points":
                verify_control(arm["final_mc_record"], replay["record"])
                if sorted(replay["played"]) != sorted(arm["played"]):
                    raise ValueError("control returned action mismatch")
            picked = tuple(sorted(replay["played"]))
            final = means[reference_index[picked]]
            best = max(means[reference_index[tuple(sorted(a))]] for a in ballot)
            outputs[model + "/" + objective] = {
                "played": replay["played"], "record": replay["record"],
                "score_units": "attacker points" if objective == "points" else "40 times model attacker level utility",
                "final_lift_vs_incumbent": float(final - reference_base),
                "selection_regret_inside_retained": float(best - final),
                "record_work_scope": "logical matrix lookups, not additional native rollouts"}
    return {"schema": "cwv-selector-objective-state-v1", "state_id": entry["id"],
            "deal_key": entry["deal_key"], "provenance": entry["provenance"],
            "source_state_sha256": digest(saved), "reference_sha256": digest(reference),
            "actions": actions, "arms": outputs,
            "folds": {name: {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in fold.items()}
                      for name, fold in folds.items()},
            "all_point_controls_reproduced": True, "native_rollouts_executed": fresh_rollouts,
            "wall_seconds": time.perf_counter() - start}


def summarize(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for arm, value in row["arms"].items():
            grouped[arm][row["deal_key"]].append(value["final_lift_vs_incumbent"])
    means = {arm: float(np.mean([np.mean(v) for v in deals.values()])) for arm, deals in grouped.items()}
    contrasts = {}
    for arm in grouped:
        if not arm.endswith("/levels"):
            continue
        baseline = arm.removesuffix("/levels") + "/points"
        differences = np.array([np.mean(grouped[arm][deal])-np.mean(grouped[baseline][deal]) for deal in sorted(grouped[arm])])
        rng = np.random.default_rng(20260907)
        boot = differences[rng.integers(len(differences), size=(10000, len(differences)))].mean(1)
        contrasts[arm] = {"level_minus_point": float(differences.mean()),
                         "exploratory_deal_bootstrap95": np.quantile(boot, [.025, .975]).tolist(),
                         "changed_submitted_moves": sum(sorted(r["arms"][arm]["played"]) != sorted(r["arms"][baseline]["played"]) for r in rows)}
    return {"scope": "FIT fixed-shortlist selector ablation; not gameplay strength or new validation",
            "aggregation": "equal source deals after within-deal selected-position averaging",
            "ci_scope": "exploratory conditional on finite reference worlds, not multiplicity-adjusted",
            "states": len(rows), "deals": len({r["deal_key"] for r in rows}),
            "all_point_controls_reproduced": all(r["all_point_controls_reproduced"] for r in rows),
            "native_rollouts_executed": sum(r["native_rollouts_executed"] for r in rows),
            "wall_seconds": sum(r["wall_seconds"] for r in rows), "arms": means, "contrasts": contrasts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    panel = json.loads(args.panel.read_text())
    old_config = json.loads((args.decisions / "config.json").read_text())
    config = {"panel_sha256": digest(panel), "decisions": str(args.decisions.resolve()),
              "references": str(args.references.resolve()), "seed": old_config["seed"],
              "selection_worlds": old_config["selection_worlds"], "report_worlds": old_config["report_worlds"],
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji")}
    config = json.loads(json.dumps(config))
    bind_output_config(args.out, config)
    rows = []
    for entry in panel["entries"]:
        filename = f"state-{entry['id']}.json"
        saved = json.loads((args.decisions / filename).read_text())
        reference = json.loads((args.references / filename).read_text())
        target = args.out / filename
        if target.exists():
            result = json.loads(target.read_text())
            if result["source_state_sha256"] != digest(saved) or result["reference_sha256"] != digest(reference):
                raise ValueError("resumed root source mismatch")
        else:
            result = run_case(entry, saved, reference, config)
            _publish(target, result)
        rows.append(result)
        print(json.dumps({"completed": len(rows), "total": len(panel["entries"]), "id": entry["id"][:8]}), flush=True)
    _publish(args.out / "summary.json", summarize(rows))


if __name__ == "__main__":
    main()

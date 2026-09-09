"""Round-clustered diagnostic readout; MC references are not ground truth."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from ..engine.cards import points as card_points
from .cwv_bury_panel import atomic_json


def interval(values):
    x = np.asarray(values, dtype=float)
    rng = np.random.default_rng(782321)
    means = np.mean(x[rng.integers(0, len(x), size=(4000, len(x)))], axis=1)
    return {"mean": float(x.mean()), "ci95": np.quantile(means, [.025, .975]).tolist(),
            "n_independent_states": len(x)}


def summarize(rows):
    result = {"schema": "cwv-bury-readout-v1", "states": len(rows),
              "scope": "rank2 DEV; one heuristic trick to model leaf; sampled-world heuristic reference",
              "not_gameplay_strength": True}
    for name in ("model", "mc", "hybrid"):
        gains, point_gains, kitty_deltas = [], [], []
        for row in rows:
            start = row["selection_worlds"]
            ref = np.asarray(row["reference_values"])[start:].mean(axis=0)
            pts = np.asarray(row["reference_attacker_points"])[start:].mean(axis=0)
            pick = row["picks"][name]
            gains.append(ref[pick] - ref[0])
            point_gains.append(pts[0] - pts[pick])
            kitty_deltas.append(sum(map(card_points, row["candidates"][pick])) -
                               sum(map(card_points, row["candidates"][0])))
        result[name] = {"signed_level_gain_vs_heuristic": interval(gains),
                        "attacker_points_reduction": interval(point_gains),
                        "buried_points_delta": interval(kitty_deltas),
                        "changed_states": sum(r["picks"][name] != 0 for r in rows)}
    correlations, model_spread, reference_spread = [], [], []
    for row in rows:
        pred = np.asarray(row["model_values"]).mean(axis=0)
        ref = np.asarray(row["reference_values"])[row["selection_worlds"]:].mean(axis=0)
        model_spread.append(float(np.ptp(pred)))
        reference_spread.append(float(np.ptp(ref)))
        if pred.std() > 0 and ref.std() > 0:
            correlations.append(float(np.corrcoef(pred, ref)[0, 1]))
    result["within_state_pearson"] = interval(correlations) if correlations else None
    result["model_candidate_range"] = interval(model_spread)
    result["reference_candidate_range"] = interval(reference_spread)
    result["hybrid_vs_mc_changed"] = sum(r["picks"]["hybrid"] != r["picks"]["mc"] for r in rows)
    result["cost"] = {"total_cpu_seconds": sum(r["cpu_seconds"] for r in rows),
                      "mean_state_wall_seconds": np.mean([r["wall_seconds"] for r in rows]).item(),
                      "mean_model_seconds": np.mean([r["model_seconds"] for r in rows]).item(),
                      "full_reference_rollouts": sum(len(r["candidates"]) * r["reference_worlds"] for r in rows)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    config = json.loads((args.directory / "config.json").read_text())
    rows = [json.loads(p.read_text()) for p in sorted(args.directory.glob("state-*.json"))]
    if len(rows) != config["states"] or any(r["config_sha256"] != config["config_sha256"] for r in rows):
        raise ValueError("panel incomplete or configuration mismatch")
    result = summarize(rows)
    atomic_json(args.directory / "summary.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

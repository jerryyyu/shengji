"""Read-only calibration analysis for saved simple-belief check references."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "simple-belief-reference-readout-v1"
CLASSES = 3
RECEIVERS = 4
CARDS = 54


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _validate_row(row: dict[str, Any], deal_key: str) -> None:
    required = {"probabilities", "reference_probabilities", "targets",
                "uncertain", "ply", "trump_rank", "is_nt", "is_banker",
                "state_key"}
    if not required.issubset(row) or row.get("deal_key", deal_key) != deal_key:
        raise ValueError("reference row is incomplete or misbound")
    p, ref, target, uncertain = (row["probabilities"],
                                 row["reference_probabilities"],
                                 row["targets"], row["uncertain"])
    if (len(p), len(ref), len(target), len(uncertain)) != (
            RECEIVERS, RECEIVERS, RECEIVERS, RECEIVERS):
        raise ValueError("reference row receiver shape differs")
    for receiver in range(RECEIVERS):
        if (len(p[receiver]), len(ref[receiver]), len(target[receiver]),
                len(uncertain[receiver])) != (CARDS, CARDS, CARDS, CARDS):
            raise ValueError("reference row card shape differs")
        for card in range(CARDS):
            probs, refs = p[receiver][card], ref[receiver][card]
            if (len(probs) != CLASSES or len(refs) != CLASSES
                    or not all(_finite(x) and 0 <= x <= 1
                               for x in probs + refs)):
                raise ValueError("reference probabilities are invalid")
            if abs(sum(probs) - 1) > 1e-5 or abs(sum(refs) - 1) > 1e-5:
                raise ValueError("reference probabilities are not normalized")
            if (type(target[receiver][card]) is not int
                    or target[receiver][card] not in range(CLASSES)):
                raise ValueError("reference target count is invalid")
            if type(uncertain[receiver][card]) is not bool:
                raise ValueError("reference uncertain mask is invalid")
    if (type(row["ply"]) is not int or row["ply"] < 0
            or type(row["is_nt"]) is not bool
            or type(row["is_banker"]) is not bool
            or not isinstance(row["state_key"], str)):
        raise ValueError("reference row metadata is invalid")


def _load(input_dir: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(input_dir)
    try:
        recipe = json.loads((root / "recipe.json").read_text())
        summary = json.loads((root / "summary.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("reference summary or recipe is unreadable") from exc
    if recipe.get("schema") != SCHEMA or summary.get("schema") != SCHEMA:
        raise ValueError("reference schema mismatch")
    paths = sorted(p for p in root.glob("*.json")
                   if p.name not in {"recipe.json", "summary.json"})
    rows: list[dict[str, Any]] = []
    seen_deals = set()
    for path in paths:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError("reference deal file is malformed")
        deal_key, identity = payload.get("deal_key"), payload.get("identity")
        if (not isinstance(deal_key, str) or not isinstance(identity, str)
                or deal_key in seen_deals):
            raise ValueError("reference deal identity is invalid")
        seen_deals.add(deal_key)
        if not payload["rows"]:
            raise ValueError("reference deal has no rows")
        for row in payload["rows"]:
            if not isinstance(row, dict):
                raise ValueError("reference row is not an object")
            _validate_row(row, deal_key)
            rows.append({"deal_key": deal_key, "identity": identity,
                         "row": row})
    skipped = summary.get("deterministic_positions_skipped", 0)
    if (type(skipped) is not int or skipped < 0
            or summary.get("deals") != len(seen_deals)
            or summary.get("positions") + skipped != len(rows)):
        raise ValueError("reference summary counts differ")
    return {"recipe": recipe, "summary": summary,
            "deals": sorted(seen_deals)}, rows


def _row_metrics(item: dict[str, Any]) -> dict[str, Any]:
    row = item["row"]
    cells = []
    for receiver in range(RECEIVERS):
        for card in range(CARDS):
            if not row["uncertain"][receiver][card]:
                continue
            target = row["targets"][receiver][card]
            truth = [float(target == cls) for cls in range(CLASSES)]
            probs = row["probabilities"][receiver][card]
            refs = row["reference_probabilities"][receiver][card]
            model_se = sum((probs[cls] - truth[cls]) ** 2 for cls in range(CLASSES))
            ref_se = sum((refs[cls] - truth[cls]) ** 2 for cls in range(CLASSES))
            cells.append((receiver, card, target, probs, refs, model_se, ref_se))
    if not cells:
        raise ValueError("reference position has no uncertain cells")
    return {"item": item, "cells": cells,
            "model_brier": _mean([c[5] for c in cells]),
            "reference_brier": _mean([c[6] for c in cells])}


def _reliability(metrics: list[dict[str, Any]], *, reference=False) -> dict[str, Any]:
    bins = [[[] for _ in range(10)] for _ in range(CLASSES)]
    for metric in metrics:
        for receiver, card, target, model_probs, ref_probs, *_ in metric["cells"]:
            probs = ref_probs if reference else model_probs
            for cls in range(CLASSES):
                bins[cls][min(9, int(float(probs[cls]) * 10))].append(
                    (float(probs[cls]), float(target == cls)))
    result = {}
    for cls, class_bins in enumerate(bins):
        output = []
        ece = 0.0
        total = sum(len(bin_) for bin_ in class_bins)
        for index, values in enumerate(class_bins):
            n = len(values)
            predicted = _mean([v[0] for v in values])
            actual = _mean([v[1] for v in values])
            gap = abs(predicted - actual) if n else 0.0
            ece += n / total * gap if total else 0.0
            output.append({"bin": index, "count": n,
                           "mean_predicted": predicted, "actual_rate": actual,
                           "absolute_gap": gap})
        result[f"class_{cls}"] = {"ece": ece, "bins": output}
    return result


def _expected_counts(metrics: list[dict[str, Any]], *, reference=False) -> dict[str, Any]:
    result = {}
    for receiver in range(RECEIVERS):
        errors = []
        for metric in metrics:
            for rec, _, target, model_probs, ref_probs, *_ in metric["cells"]:
                probs = ref_probs if reference else model_probs
                if rec == receiver:
                    errors.append(sum(cls * probs[cls] for cls in range(CLASSES))
                                  - target)
        result[f"receiver_{receiver}"] = {
            "cells": len(errors), "signed_error": _mean(errors),
            "absolute_error": _mean([abs(error) for error in errors])}
    return result


def _provenance(metric: dict[str, Any]) -> dict[str, Any]:
    item, row = metric["item"], metric["item"]["row"]
    return {"deal_key": item["deal_key"], "identity": item["identity"],
            "state_key": row["state_key"], "ply": row["ply"],
            "seat": row.get("seat"), "trump_rank": row["trump_rank"],
            "is_nt": row["is_nt"], "is_banker": row["is_banker"]}


def _top_positions(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    from ..rl.encode import CARD_INDEX
    card_names = {index: card for card, index in CARD_INDEX.items()}

    def explain(metric, harmful):
        cells = [c for c in metric['cells'] if (c[5]-c[6] > 0 if harmful else c[5]-c[6] < 0)]
        explanations = sorted(cells, key=lambda c: c[5]-c[6], reverse=harmful)[:3]
        return [{"receiver": c[0], "card_index": c[1], 'card': card_names[c[1]],
                 "target": c[2], "model_probability": c[3],
                 "reference_probability": c[4],
                 "truth": [int(c[2] == cls) for cls in range(CLASSES)],
                 "squared_error_difference": c[5] - c[6]}
                for c in explanations]

    def position(metric, harmful):
        return {**_provenance(metric),
                "model_raw_brier": metric["model_brier"],
                "reference_raw_brier": metric["reference_brier"],
                "difference": metric["model_brier"] - metric["reference_brier"],
                "explanation_direction": 'higher_error' if harmful else 'lower_error',
                "explanations": explain(metric, harmful)}

    ordered = sorted(metrics, key=lambda m: m["model_brier"] - m["reference_brier"])
    return {"helpful": [position(m, False) for m in ordered
                         if m['model_brier'] < m['reference_brier']][:5],
            "harmful": [position(m, True) for m in reversed(ordered)
                         if m['model_brier'] > m['reference_brier']][:5]}


def _paired(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    def summary(group):
        model = [m["model_brier"] for m in group]
        reference = [m["reference_brier"] for m in group]
        return {"positions": len(group), "model_raw_brier": _mean(model),
                "reference_raw_brier": _mean(reference),
                "difference": _mean([a - b for a, b in zip(model, reference)])}

    groups = {"all": metrics,
              "early_ply_0": [m for m in metrics if m["item"]["row"]["ply"] == 0],
              "later_ply": [m for m in metrics if m["item"]["row"]["ply"] != 0],
              "nt": [m for m in metrics if m["item"]["row"]["is_nt"]],
              "suited": [m for m in metrics if not m["item"]["row"]["is_nt"]]}
    deals = {}
    for key in sorted({m["item"]["deal_key"] for m in metrics}):
        selected = [m for m in metrics if m["item"]["deal_key"] == key]
        deals[key] = summary(selected)
    return {"overall_and_phase": {key: summary(value) for key, value in groups.items()},
            "per_deal": deals}


def analyze(input_dir: str | Path) -> dict[str, Any]:
    binding, rows = _load(input_dir)
    metrics = [_row_metrics(item) for item in rows
               if any(any(bits) for bits in item["row"]["uncertain"])]
    return {
        "schema": "simple-belief-calibration-v1",
        "input": str(input_dir),
        "reference_schema": SCHEMA,
        "positions": len(metrics),
        "uncertain_cells": sum(len(m["cells"]) for m in metrics),
        "provenance": binding,
        "reliability": _reliability(metrics),
        "reference_reliability_raw_mc": _reliability(metrics, reference=True),
        "expected_card_count": _expected_counts(metrics),
        "reference_expected_card_count": _expected_counts(metrics, reference=True),
        "paired_raw_brier": _paired(metrics),
        "top_positions": _top_positions(metrics),
        "note": "Raw MC probabilities are used for reference calibration; no MC-noise correction, confidence interval, or strength claim is made.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite existing calibration output")
    result = analyze(args.input)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"positions": result["positions"],
                      "uncertain_cells": result["uncertain_cells"],
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()

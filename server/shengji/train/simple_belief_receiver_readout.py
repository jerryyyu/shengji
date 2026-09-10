"""Equal-deal readout of retained simple-belief predictions.

This is a read-only diagnostic.  It joins the saved ordinary-reference and
R4 outputs on both deal and state, then scores uncertain ownership cells only.
It does not fit a model or re-run either predictor.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "simple-belief-receiver-readout-v1"
REFERENCE_SCHEMA = "simple-belief-reference-readout-v1"
R4_SCHEMA = "simple-belief-r4-compare-v1"
ARM_PRIMARY = "synthetic-primary"
ARM_CONTROL = "hard-geometry-label-permutation"
RECEIVER_NAMES = ("receiver_0", "receiver_1", "receiver_2", "kitty")
GROUP_RECEIVERS = {"opponents": (0, 1, 2), "kitty": (3,), "all": (0, 1, 2, 3)}
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20260910


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"unreadable JSON: {path}") from exc


def _deal_files(root: Path, *, schema: str) -> dict[str, dict[str, Any]]:
    recipe = _read_json(root / "recipe.json")
    summary = _read_json(root / "summary.json")
    if not isinstance(recipe, dict) or recipe.get("schema") != schema:
        raise ValueError(f"saved readout recipe schema mismatch: {root}")
    # The retained R4 comparator predates the summary schema field; its
    # recipe remains the authoritative schema binding.  Reject an explicit
    # wrong field while accepting that historical omission.
    if (not isinstance(summary, dict)
            or ("schema" in summary and summary.get("schema") != schema)):
        raise ValueError(f"saved readout summary schema mismatch: {root}")
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        if path.name in {"recipe.json", "summary.json"}:
            continue
        payload = _read_json(path)
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError(f"saved deal file is malformed: {path}")
        key = payload.get("deal_key")
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("saved deal keys must be distinct strings")
        result[key] = payload
    if summary.get("deals") != len(result):
        raise ValueError("saved readout deal population differs from summary")
    return result


def _array(value: Any, shape: tuple[int, ...], field: str) -> np.ndarray:
    try:
        result = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not an array") from exc
    if result.shape != shape:
        raise ValueError(f"{field} shape differs")
    if not np.isfinite(result.astype(float, copy=False)).all():
        raise ValueError(f"{field} contains non-finite values")
    return result.astype(float, copy=False)


def _row_arrays(reference_row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    required = {"probabilities", "reference_probabilities", "targets", "uncertain", "state_key"}
    if not required.issubset(reference_row):
        raise ValueError("reference row is incomplete")
    shape = (4, 54, 3)
    model = _array(reference_row["probabilities"], shape, "newmodel probabilities")
    ordinary = _array(reference_row["reference_probabilities"], shape,
                      "ordinary probabilities")
    targets = np.asarray(reference_row["targets"])
    uncertain = np.asarray(reference_row["uncertain"])
    if targets.shape != (4, 54) or uncertain.shape != (4, 54):
        raise ValueError("reference target/mask shape differs")
    if not np.issubdtype(targets.dtype, np.integer) or ((targets < 0) | (targets > 2)).any():
        raise ValueError("reference targets are invalid")
    if uncertain.dtype != np.dtype(bool):
        raise ValueError("reference uncertain mask is invalid")
    for name, probabilities in (("newmodel", model), ("ordinary", ordinary)):
        if (probabilities < -1e-9).any() or (probabilities > 1 + 1e-9).any():
            raise ValueError(f"{name} probabilities are invalid")
        if not np.allclose(probabilities.sum(axis=-1), 1, atol=1e-5):
            raise ValueError(f"{name} probabilities are not normalized")
    return model, ordinary, targets.astype(int), uncertain


def corrected_brier(raw_brier: float, correction: float) -> float:
    """Apply the finite-MC Brier correction with its unbiased sign."""
    if not math.isfinite(float(raw_brier)) or not math.isfinite(float(correction)):
        raise ValueError("Brier values must be finite")
    return float(raw_brier) - float(correction)


def _scores(probabilities: np.ndarray, targets: np.ndarray, uncertain: np.ndarray,
            worlds: int) -> tuple[np.ndarray, np.ndarray]:
    truth = np.eye(3, dtype=float)[targets]
    score = np.square(probabilities - truth).sum(axis=-1)
    correction = (probabilities * (1 - probabilities)).sum(axis=-1) / (worlds - 1)
    return score, correction


def _r4_arrays(row: dict[str, Any], arm: str) -> np.ndarray:
    arms = row.get("arms")
    if not isinstance(arms, dict) or arm not in arms or not isinstance(arms[arm], dict):
        raise ValueError(f"R4 arm missing: {arm}")
    probabilities = _array(arms[arm].get("probabilities"), (4, 54, 3),
                          f"R4 {arm} probabilities")
    if (probabilities < -1e-9).any() or (probabilities > 1 + 1e-9).any():
        raise ValueError(f"R4 {arm} probabilities are invalid")
    if not np.allclose(probabilities.sum(axis=-1), 1, atol=1e-5):
        raise ValueError(f"R4 {arm} probabilities are not normalized")
    return probabilities


def _bootstrap(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    values_array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = values_array[rng.integers(0, len(values_array), (BOOTSTRAP_SAMPLES, len(values_array)))]
    return {"deals": len(values), "mean_delta": float(values_array.mean()),
            "bootstrap95": np.quantile(draws.mean(axis=1), [0.025, 0.975]).tolist(),
            "bootstrap_samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED}


def _summarize(deal_cells: dict[str, list[dict[str, list[tuple[float, float, float, float, float]]]]],
               group: str, receiver_set: tuple[int, ...] | None = None) -> dict[str, Any]:
    """Summarize cells with equal position, then equal deal weighting."""
    receiver_set = GROUP_RECEIVERS[group] if receiver_set is None else receiver_set
    per_deal: dict[str, dict[str, float]] = {}
    absent_rows = 0
    uncertain_cells = 0
    positions = 0
    for deal, rows in deal_cells.items():
        position_means: list[np.ndarray] = []
        selected_rows = 0
        for row in rows:
            row_selected = [cell for receiver, name in enumerate(RECEIVER_NAMES)
                            if receiver in receiver_set for cell in row[name]]
            if not row_selected:
                absent_rows += 1
            else:
                selected_rows += 1
                # A position contributes one mean regardless of its number
                # of uncertain cells.  Cell totals below remain diagnostic
                # counts and never become metric weights.
                position_means.append(np.asarray(row_selected, dtype=float).mean(axis=0))
                uncertain_cells += len(row_selected)
        if not position_means:
            continue
        positions += selected_rows
        values = np.asarray(position_means, dtype=float)
        per_deal[deal] = {name: float(values[:, index].mean()) for index, name in enumerate(
            ("newmodel", "ordinary_raw", "ordinary_debiased", ARM_PRIMARY, ARM_CONTROL))}
    result: dict[str, Any] = {
        "deals": len(per_deal), "positions": positions, "uncertain_cells": uncertain_cells,
        "absent_receiver_group_rows_skipped": absent_rows,
        "weighting": {
            "within_position": "equal_uncertain_cell_mean",
            "within_deal": "equal_position_mean",
            "across_deals": "equal_deal_mean",
        },
        "equal_deal_mean_brier": ({name: float(np.mean([row[name] for row in per_deal.values()]))
                                   for name in ("newmodel", "ordinary_raw", "ordinary_debiased",
                                                ARM_PRIMARY, ARM_CONTROL)} if per_deal else None),
        "per_deal": per_deal,
    }
    if per_deal:
        new = [row["newmodel"] for row in per_deal.values()]
        for comparison, key in (("ordinary", "ordinary_debiased"),
                                (ARM_PRIMARY, ARM_PRIMARY), (ARM_CONTROL, ARM_CONTROL)):
            result.setdefault("paired", {})[f"new_vs_{comparison}"] = _bootstrap(
                [a - b for a, b in zip(new, [row[key] for row in per_deal.values()])])
    else:
        result["paired"] = {f"new_vs_{name}": None for name in ("ordinary", ARM_PRIMARY, ARM_CONTROL)}
    return result


def analyze(reference: str | Path, r4: str | Path) -> dict[str, Any]:
    """Analyze two retained directories without invoking a model or sampler."""
    reference_root, r4_root = Path(reference), Path(r4)
    reference_deals = _deal_files(reference_root, schema=REFERENCE_SCHEMA)
    r4_deals = _deal_files(r4_root, schema=R4_SCHEMA)
    if set(reference_deals) != set(r4_deals):
        raise ValueError("deal join population differs")
    ref_recipe = _read_json(reference_root / "recipe.json")
    worlds = ref_recipe.get("worlds", 256)
    if type(worlds) is not int or worlds < 2:
        raise ValueError("ordinary reference world count is invalid")

    # Each receiver's list contains one entry per state row.  Empty lists are
    # retained so the report can distinguish an absent receiver group from a
    # zero-valued score.
    cells: dict[str, list[dict[str, list[tuple[float, float, float, float, float]]]]] = {}
    total_positions = 0
    deterministic_positions = 0
    deterministic_cells = 0
    for deal in sorted(reference_deals):
        ref_rows = reference_deals[deal]["rows"]
        r4_rows = r4_deals[deal]["rows"]
        ref_by_state = {}
        r4_by_state = {}
        for row in ref_rows:
            if not isinstance(row, dict) or not isinstance(row.get("state_key"), str):
                raise ValueError("reference state join key is invalid")
            if row["state_key"] in ref_by_state:
                raise ValueError("duplicate reference state join key")
            ref_by_state[row["state_key"]] = row
        for row in r4_rows:
            if not isinstance(row, dict) or not isinstance(row.get("state_key"), str):
                raise ValueError("R4 state join key is invalid")
            if row["state_key"] in r4_by_state:
                raise ValueError("duplicate R4 state join key")
            r4_by_state[row["state_key"]] = row
        # The original R4 comparator deliberately omitted fully deterministic
        # positions.  Those reference rows are still counted as skipped, but
        # every uncertain reference state must have exactly one R4 row (and R4
        # must not invent a state).
        uncertain_ref_states = set()
        for state, row in ref_by_state.items():
            if not isinstance(row, dict):
                raise ValueError("reference row is not an object")
            if np.asarray(row.get("uncertain")).shape != (4, 54):
                raise ValueError("reference target/mask shape differs")
            if np.asarray(row["uncertain"]).astype(bool).any():
                uncertain_ref_states.add(state)
        if uncertain_ref_states != set(r4_by_state):
            raise ValueError(f"state join population differs for {deal}")
        cells[deal] = []
        for state in sorted(ref_by_state):
            if state not in r4_by_state:
                # No R4 payload is needed for an all-deterministic row.
                total_positions += 1
                deterministic_positions += 1
                deterministic_cells += 4 * 54
                continue
            ref_row, r4_row = ref_by_state[state], r4_by_state[state]
            model, ordinary, targets, uncertain = _row_arrays(ref_row)
            total_positions += 1
            n_uncertain = int(uncertain.sum())
            if not n_uncertain:
                deterministic_positions += 1
            deterministic_cells += int((~uncertain).sum())
            model_score, _ = _scores(model, targets, uncertain, worlds)
            ordinary_score, correction = _scores(ordinary, targets, uncertain, worlds)
            primary_score, control_score = (
                _scores(_r4_arrays(r4_row, arm), targets, uncertain, worlds)[0]
                for arm in (ARM_PRIMARY, ARM_CONTROL))
            row_cells: dict[str, list[tuple[float, float, float, float, float]]] = {}
            for receiver, name in enumerate(RECEIVER_NAMES):
                mask = uncertain[receiver]
                row_cells[name] = [
                    (float(model_score[receiver, card]), float(ordinary_score[receiver, card]),
                     corrected_brier(float(ordinary_score[receiver, card]),
                                     float(correction[receiver, card])),
                     float(primary_score[receiver, card]), float(control_score[receiver, card]))
                    for card in np.flatnonzero(mask)]
            cells[deal].append(row_cells)

    # Convert receiver-wise cells to the shape expected by _summarize: a row
    # is represented by receiver lists.  The deal-level aggregate remains
    # equal-weighted regardless of how many states each deal contributes.
    summaries = {group: _summarize(cells, group) for group in ("all", "opponents", "kitty")}
    per_receiver = {name: _summarize(cells, "all", (index,))
                    for index, name in enumerate(RECEIVER_NAMES)}

    return {
        "schema": SCHEMA,
        "reference": str(reference), "r4": str(r4),
        "ordinary_worlds": worlds,
        "weighting": {
            "within_position": "equal_uncertain_cell_mean",
            "within_deal": "equal_position_mean",
            "across_deals": "equal_deal_mean",
        },
        "population": {
            "deals": len(cells), "positions": total_positions,
            "deterministic_positions_skipped": deterministic_positions,
            "deterministic_cells_skipped": deterministic_cells,
            "uncertain_cells": summaries["all"]["uncertain_cells"],
        },
        "equal_deal_mean_brier": {group: summaries[group]["equal_deal_mean_brier"]
                                   for group in ("all", "opponents", "kitty")},
        "opponents": summaries["opponents"], "kitty": summaries["kitty"],
        "per_receiver": per_receiver,
        "paired": {group: summaries[group]["paired"] for group in ("all", "opponents", "kitty")}
                   | {name: per_receiver[name]["paired"] for name in RECEIVER_NAMES},
        "note": "Saved internal belief check only; old-R4 training overlap remains pending, so generalization is not independently verified.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--r4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite existing output")
    result = analyze(args.reference, args.r4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"schema": SCHEMA, "deals": result["population"]["deals"],
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()

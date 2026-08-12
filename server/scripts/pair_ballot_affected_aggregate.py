#!/usr/bin/env python3
"""Aggregate reusable DEV/CALIB pair-retention diagnostics by deal cluster.

This intentionally reports estimates and uncertainty without a SELECT_NONE
terminal.  Exploration should route the next mechanism:

* positive policy effect -> test natural-dose composition;
* positive inserted-pair headroom but neutral policy -> improve selection;
* neutral/negative headroom -> do not force pairs into the fixed ballot.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pair_ballot_affected_eval as EVAL
import pair_ballot_affected_states as STATES


SCHEMA = "pair-ballot-affected-eval-aggregate-v1"
METRICS = (
    "retained_policy_minus_current",
    "best_inserted_pair_minus_current",
)


def _finite_number(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _validate_result(row: object, *, split: str,
                     report_worlds: int) -> None:
    if not isinstance(row, dict) or row.get("schema") != EVAL.SCHEMA:
        raise EVAL.EvalRefused("pair evaluation result schema drift")
    body = dict(row)
    observed_sha = body.pop("result_sha256", None)
    if observed_sha != STATES.sha256_bytes(STATES.canonical_json(body)):
        raise EVAL.EvalRefused("pair evaluation result digest drift")
    if (row.get("split") != split
            or row.get("diagnostic_only") is not True
            or row.get("strength_claim") is not False
            or row.get("production_promotion") is not False
            or row.get("production_deployment") is not False
            or row.get("external_report", {}).get("worlds") != report_worlds
            or set(row.get("estimands", {})) != set(METRICS)
            or any(not _finite_number(row["estimands"][metric])
                   for metric in METRICS)):
        raise EVAL.EvalRefused("pair evaluation result content/authority drift")


def load_shard(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise EVAL.EvalRefused("pair evaluation shard missing/nonregular")
    payload = json.loads(path.read_bytes())
    if payload.get("schema") != EVAL.SHARD_SCHEMA:
        raise EVAL.EvalRefused("pair evaluation shard schema drift")
    body = dict(payload)
    observed_sha = body.pop("artifact_sha256", None)
    if observed_sha != STATES.sha256_bytes(STATES.canonical_json(body)):
        raise EVAL.EvalRefused("pair evaluation shard digest drift")
    rows = payload.get("results")
    split = payload.get("split")
    report_worlds = payload.get("report_worlds")
    if (split not in EVAL.ALLOWED_SPLITS
            or not isinstance(rows, list)
            or payload.get("rows") != len(rows)
            or isinstance(report_worlds, bool)
            or not isinstance(report_worlds, int) or report_worlds <= 0
            or payload.get("diagnostic_only") is not True
            or payload.get("strength_claim") is not False
            or payload.get("production_promotion") is not False
            or payload.get("production_deployment") is not False):
        raise EVAL.EvalRefused("pair evaluation shard content/authority drift")
    for row in rows:
        _validate_result(row, split=split, report_worlds=report_worlds)
    return payload


def weighted_cluster_stats(rows: list[dict], metric: str,
                           band_weights: dict[str, float]) -> dict:
    if metric not in METRICS or not rows:
        raise EVAL.EvalRefused("unknown/empty pair diagnostic metric")
    by_band = defaultdict(list)
    for row in rows:
        by_band[row["band"]].append(row)
    if set(by_band) != set(STATES.BANDS) or set(band_weights) != set(STATES.BANDS):
        raise EVAL.EvalRefused("pair diagnostic band population drift")
    if (any(not _finite_number(weight) or weight <= 0
            for weight in band_weights.values())
            or not math.isclose(sum(band_weights.values()), 1.0,
                                abs_tol=1e-12)):
        raise EVAL.EvalRefused("pair diagnostic natural weights drift")
    means = {
        band: sum(row["estimands"][metric] for row in values) / len(values)
        for band, values in by_band.items()
    }
    estimate = sum(band_weights[band] * means[band] for band in STATES.BANDS)
    influence = defaultdict(float)
    observation_weights = {}
    for band in STATES.BANDS:
        weight = band_weights[band] / len(by_band[band])
        observation_weights[band] = weight
        for row in by_band[band]:
            influence[int(row["deal_seed"])] += (
                weight * (row["estimands"][metric] - means[band]))
    clusters = len(influence)
    se = (math.sqrt(clusters / (clusters - 1)
                    * sum(value * value for value in influence.values()))
          if clusters >= 2 else float("inf"))
    return {
        "metric": metric,
        "rows": len(rows),
        "deal_clusters": clusters,
        "natural_weighted_mean": estimate,
        "cluster_robust_se": se,
        "ci95": [estimate - 1.96 * se, estimate + 1.96 * se],
        "band_weights": dict(band_weights),
        "observation_weights": observation_weights,
        "by_band": {
            band: {"n": len(by_band[band]), "mean": means[band]}
            for band in STATES.BANDS
        },
    }


def diagnostic_route(policy_mean: float, source_mean: float) -> str:
    if source_mean > 0 and policy_mean > 0:
        return "POLICY_AND_SOURCE_PROMISING_TEST_NATURAL_DOSE"
    if source_mean > 0:
        return "SOURCE_PROMISING_SELECTOR_NOT_EXPLOITING"
    if policy_mean > 0:
        return "POLICY_POSITIVE_WITHOUT_INSERTED_PAIR_HEADROOM_AUDIT_EVICTIONS"
    return "FIXED_WIDTH_RETENTION_NOT_PROMISING_TRY_CONTEXTUAL_PAIR_SOURCE"


def aggregate(*, population: Path, shard_paths: list[Path],
              split: str, out: Path) -> dict:
    if split not in EVAL.ALLOWED_SPLITS or not shard_paths:
        raise EVAL.EvalRefused("aggregate requires DEV/CALIB and shard inputs")
    source = EVAL.load_population(population)
    shards = [load_shard(path) for path in shard_paths]
    shard_count = shards[0].get("shard_count")
    report_worlds = shards[0].get("report_worlds")
    expected_source_sha = STATES.sha256_file(population)
    indices = []
    rows = []
    for shard in shards:
        if (shard.get("split") != split
                or shard.get("shard_count") != shard_count
                or shard.get("report_worlds") != report_worlds
                or shard.get("source_file_sha256") != expected_source_sha
                or shard.get("source_artifact_sha256")
                != source["artifact_sha256"]):
            raise EVAL.EvalRefused("pair aggregate shard cohort drift")
        indices.append(shard.get("shard_index"))
        rows.extend(shard["results"])
    if (not isinstance(shard_count, int) or shard_count <= 0
            or sorted(indices) != list(range(shard_count))):
        raise EVAL.EvalRefused("pair aggregate shard population incomplete")
    expected = {row["state_id"]: row for row in source["states"]
                if row["split"] == split}
    observed = {row["state_id"]: row for row in rows}
    if len(observed) != len(rows) or set(observed) != set(expected):
        raise EVAL.EvalRefused("pair aggregate state population incomplete")
    for state_id, result in observed.items():
        if result["state_sha256"] != expected[state_id]["state_sha256"]:
            raise EVAL.EvalRefused("pair aggregate state binding drift")

    weights = source.get("search_eligible_weights")
    stats = {metric: weighted_cluster_stats(rows, metric, weights)
             for metric in METRICS}
    counts = Counter(row["band"] for row in rows)
    dose = {
        "states": len(rows),
        "unique_deals": len({row["deal_seed"] for row in rows}),
        "by_band": dict(sorted(counts.items())),
        "policy_action_changes": sum(row["policy_action_changed"] for row in rows),
        "retained_raw_winner_inserted": sum(
            row["retained_raw_winner_is_inserted"] for row in rows),
        "current_raw_winner_evicted": sum(
            row["current_raw_winner_was_evicted"] for row in rows),
    }
    policy_mean = stats["retained_policy_minus_current"]["natural_weighted_mean"]
    source_mean = stats[
        "best_inserted_pair_minus_current"]["natural_weighted_mean"]
    payload = {
        "schema": SCHEMA,
        "split": split,
        "source_file_sha256": expected_source_sha,
        "source_artifact_sha256": source["artifact_sha256"],
        "shard_count": shard_count,
        "report_worlds": report_worlds,
        "dose": dose,
        "metrics": stats,
        "diagnostic_route": diagnostic_route(policy_mean, source_mean),
        "terminal_selection": False,
        "diagnostic_only": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["artifact_sha256"] = STATES.sha256_bytes(STATES.canonical_json(payload))
    STATES._write_exclusive(out, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--split", choices=EVAL.ALLOWED_SPLITS, required=True)
    parser.add_argument("--shard", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        aggregate(
            population=args.population, shard_paths=args.shard,
            split=args.split, out=args.out)
    except (EVAL.EvalRefused, STATES.CaptureRefused, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()

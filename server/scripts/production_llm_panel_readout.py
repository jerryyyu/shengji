"""Read a sealed nine-row Sol/PT-Sol W32 benchmark panel.

This is a consumer of :mod:`w32_llm_benchmark`; it never constructs a game,
loads a model, or invokes a provider.  The producer's ``signed_levels`` are
from the opponent perspective, so this consumer negates them to report
policy-minus-Sol.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Mapping, Sequence

from shengji.luna.benchmark_failure_protocol import (
    FAIL_STOP, PRESERVE_ILLEGAL, attempt_disposition,
)
from shengji.luna.benchmark_forfeit_contrast import aligned_forfeit_values


PANEL_SCHEMA = "production-llm-panel-readout-v1"
SCHEMA = "w32-llm-benchmark-v1"
POLICIES = ("smv3-pv", "soft-pv", "js-m1-shortlist", "m1-prior",
            "w32-original", "mc-lcb", "mc-strong", "mc", "smart")
INFORMATION = {"sol": "actor-only", "pt_sol": "perfect"}
SEED_COUNT = 10
MIRROR_COUNT = SEED_COUNT * 2 * 2
BOOTSTRAP_SEED = 20261002
BOOTSTRAP_REPLICATES = 2000


class PanelReadoutError(ValueError):
    """The supplied panel is not an admitted producer-shaped panel."""


def _bootstrap(values: Sequence[float], *, seed: int) -> list[float] | None:
    """Use the benchmark producer's fixed 2,000-resample percentile rule."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(statistics.fmean(rng.choices(list(values), k=n))
                   for _ in range(2000))
    return [means[49], means[1950]]


def _read_json(path: Path, *, label: str) -> object:
    if path.is_symlink() or not path.is_file():
        raise PanelReadoutError(f"{label} must be a regular file: {path}")
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PanelReadoutError(f"invalid JSON in {label}: {path}") from exc


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PanelReadoutError(f"{label} must be an object")
    return value


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


def _stats(values: Sequence[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None,
                "min": None, "max": None}
    ordered = sorted(float(value) for value in values)
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * .95) - 1))
    return {"count": len(ordered), "mean": statistics.fmean(ordered),
            "p50": statistics.median(ordered), "p95": ordered[p95_index],
            "min": ordered[0], "max": ordered[-1]}


def _usage(calls: Sequence[object]) -> dict[str, object]:
    totals: list[int] = []
    unknown = 0
    for call in calls:
        if not isinstance(call, Mapping):
            unknown += 1
            continue
        usage = call.get("usage")
        if (not isinstance(usage, Mapping)
                or type(usage.get("input_tokens")) is not int
                or type(usage.get("output_tokens")) is not int
                or usage["input_tokens"] < 0 or usage["output_tokens"] < 0):
            unknown += 1
            continue
        totals.append(usage["input_tokens"] + usage["output_tokens"])
    return {"total_tokens": sum(totals) if totals else None,
            "known_calls": len(totals), "unknown_calls": unknown,
            "complete": bool(totals) and not unknown}


def _transport_health(calls: Sequence[object]) -> dict[str, object]:
    """Census recorded notices, not provider authentication or score filtering.

    Older receipts lack this telemetry: absent is unknown, never zero.
    A malformed optional field does not erase valid game outcomes.
    """
    known = unknown = malformed = events = affected = 0
    for call in calls:
        if not isinstance(call, Mapping) or "recovered_reconnects" not in call:
            unknown += 1
            continue
        notices = call["recovered_reconnects"]
        if (type(notices) is not list or any(
                type(event) is not dict or set(event) != {"type", "message"}
                or event["type"] != "error" or type(event["message"]) is not str
                for event in notices)):
            malformed += 1
            unknown += 1
            continue
        known += 1
        events += len(notices)
        affected += bool(notices)
    return {"known_calls": known, "unknown_calls": unknown,
            "malformed_calls": malformed,
            "recorded_reconnect_events": events if known else None,
            "calls_with_recorded_reconnects": affected if known else None,
            "complete": bool(known) and not unknown}


def _rollout_value(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, list):
        return len(value)
    return None


def _rollouts(row: Mapping[str, object]) -> int | None:
    """Extract legacy rollout use only; absent is unknown."""
    for key in ("rollout_calls", "rollout_count", "rollouts_used", "rollouts"):
        if key in row:
            value = _rollout_value(row[key])
            if value is not None:
                return value
    usage = row.get("rollout_usage")
    if isinstance(usage, Mapping):
        for key in ("calls", "count", "rollout_calls"):
            if key in usage:
                value = _rollout_value(usage[key])
                if value is not None:
                    return value
    found: list[int] = []
    for call in row.get("calls", ()) if isinstance(row.get("calls"), list) else ():
        if isinstance(call, Mapping):
            for key in ("rollout_calls", "rollout_count", "rollouts_used", "rollouts"):
                if key in call:
                    value = _rollout_value(call[key])
                    if value is not None:
                        found.append(value)
                        break
    if found:
        return sum(found)
    return None


ROLLOUT_FIELDS = ("requested_batches", "attempted_evaluations",
                  "completed_evaluations", "completed_world_rollouts")


def _rollout_stats(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in ROLLOUT_FIELDS:
        values: list[int] = []
        for row in rows:
            usage = row.get("rollout_usage")
            value = usage.get(field) if isinstance(usage, Mapping) else None
            if type(value) is int and value >= 0:
                values.append(value)
        result[field] = {"total": sum(values) if values else None,
                         "recorded_mirrors": len(values),
                         "unknown_mirrors": len(rows) - len(values)}
    # Compatibility for synthetic/older producer-shaped rows. Never turn an
    # absent modern field into zero.
    if not any(result[field]["recorded_mirrors"] for field in ROLLOUT_FIELDS):
        legacy = [_rollouts(row) for row in rows]
        known = [value for value in legacy if value is not None]
        result["legacy_total"] = sum(known) if known else None
        result["legacy_recorded_mirrors"] = len(known)
        result["legacy_unknown_mirrors"] = len(rows) - len(known)
    return result


def _win_rates(values: Sequence[float]) -> dict[str, object]:
    wins = sum(value > 0 for value in values)
    ties = sum(value == 0 for value in values)
    losses = sum(value < 0 for value in values)
    return {"wins": wins, "ties": ties, "losses": losses,
            "rate": (wins / len(values) if values else None),
            "win_rate": (wins / len(values) if values else None),
            "n": len(values),
            "complete": len(values)}


def _contrast(values: Sequence[float], *, seed: int = BOOTSTRAP_SEED) -> dict[str, object]:
    return {"count": len(values), "mean": statistics.fmean(values) if values else None,
            "ci95": _bootstrap(values, seed=seed),
            "values": list(values),
            "uncertainty": "wide/undefined with fewer than two completed deals"
            if len(values) < 2 else "iid deal-cluster bootstrap"}


CAMPAIGN_SCHEMA = "sol-nine-policy-campaign-v1"


def _campaign_context(directory: Path) -> dict[str, object] | None:
    """Load the launcher's sealed campaign/root identities when available."""
    candidate = directory.parent / "config.json"
    if not candidate.is_file() or candidate.is_symlink():
        return None
    campaign = _mapping(_read_json(candidate, label="campaign config"),
                        label="campaign config")
    recovery = campaign.get("schema") == "sol-six-row-recovery-v1"
    if campaign.get("schema") not in (CAMPAIGN_SCHEMA, "sol-nine-policy-campaign-v2", "sol-six-row-recovery-v1"):
        return None
    seeds = campaign.get("seeds")
    if (not isinstance(seeds, list) or len(seeds) != SEED_COUNT
            or any(type(seed) is not int for seed in seeds)
            or len(set(seeds)) != SEED_COUNT):
        raise PanelReadoutError("campaign config must contain ten unique integer seeds")
    if campaign.get("rows") != list(POLICIES[3:] if recovery else POLICIES):
        raise PanelReadoutError("campaign config rows are not the authorized panel")
    prepared_dir = campaign.get("prepared_roots")
    if not isinstance(prepared_dir, str):
        raise PanelReadoutError("campaign config has no prepared-root directory")
    root_result = Path(prepared_dir)
    if not root_result.is_absolute():
        root_result = candidate.parent / root_result
    root_result = root_result / "result.json"
    if root_result.is_symlink() or not root_result.is_file():
        raise PanelReadoutError("campaign prepared-root result.json is unavailable")
    raw = root_result.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    if source_sha != campaign.get("prepared_roots_sha256"):
        raise PanelReadoutError("campaign prepared-root source SHA mismatch")
    source = _mapping(json.loads(raw), label="campaign root result")
    root_hashes = source.get("roots")
    if not isinstance(root_hashes, Mapping):
        raise PanelReadoutError("campaign root result has no root hashes")
    expected = {str(seed) for seed in seeds}
    if set(root_hashes) != expected or any(not isinstance(value, str) for value in root_hashes.values()):
        raise PanelReadoutError("campaign root result does not cover the ten seeds")
    return {"seeds": list(seeds), "source_result_sha256": source_sha,
            "root_hashes": dict(root_hashes), "campaign": dict(campaign)}


def _validate_config(benchmark_id: str, config: Mapping[str, object],
                     campaign: Mapping[str, object] | None) -> tuple[list[int], str, dict[str, object], Mapping[str, object]]:
    seeds = config.get("seeds")
    if (not isinstance(seeds, list) or len(seeds) != SEED_COUNT
            or any(type(seed) is not int for seed in seeds)
            or len(set(seeds)) != SEED_COUNT):
        raise PanelReadoutError(f"{benchmark_id}: config must contain ten unique integer seeds")
    info = config.get("information")
    if (config.get("models") != ["sol"] or not isinstance(info, list)
            or set(info) != {"actor-only", "perfect"} or len(info) != 2):
        raise PanelReadoutError(f"{benchmark_id}: only sol actor-only/perfect arms are admitted")
    recipe = _mapping(config.get("baseline_recipe"), label=f"{benchmark_id} recipe")
    if (recipe.get("benchmark_id") != benchmark_id
            or not isinstance(config.get("policy"), str)
            or not config.get("policy")):
        raise PanelReadoutError(f"{benchmark_id}: benchmark identity mismatch")
    prepared = config.get("prepared_roots_from")
    prepared = _mapping(prepared, label=f"{benchmark_id} prepared-root config")
    source_sha = prepared.get("result_sha256")
    root_hashes = prepared.get("root_hashes")
    if (not isinstance(source_sha, str) or len(source_sha) != 64
            or not isinstance(root_hashes, Mapping)
            or set(root_hashes) != {str(seed) for seed in seeds}
            or any(not isinstance(value, str) for value in root_hashes.values())):
        raise PanelReadoutError(f"{benchmark_id}: prepared-root source identity is malformed")
    if campaign is not None and (source_sha != campaign["source_result_sha256"]
                                 or dict(root_hashes) != campaign["root_hashes"]):
        raise PanelReadoutError(f"{benchmark_id}: campaign/root identities disagree")
    return list(seeds), source_sha, dict(root_hashes), recipe


def _validate_row_report(benchmark_id: str, directory: Path | None,
                         *, campaign: Mapping[str, object] | None = None,
                         not_run: bool = False,
                         report_data: Mapping[str, object] | None = None) -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
    if report_data is not None and (directory is not None or not_run):
        raise PanelReadoutError('in-memory report cannot be mixed with filesystem/partial input')
    if (directory is not None and not directory.exists()
            and not directory.is_symlink() and campaign is not None):
        directory, not_run = None, True
    if directory is not None and (directory.is_symlink() or not directory.is_dir()):
        raise PanelReadoutError(f"row directory must be a regular directory: {directory}")
    report: Mapping[str, object] = {}
    config: Mapping[str, object]
    terminal = False
    if report_data is not None or (directory is not None and (directory / "result.json").is_file()):
        report = _mapping(report_data if report_data is not None else
                          _read_json(directory / "result.json", label="row result.json"),
                          label="row result")
        if report.get("schema") != SCHEMA or report.get("mode") != "run":
            raise PanelReadoutError(f"{benchmark_id}: result is not a terminal W32 run")
        config = _mapping(report.get("config"), label=f"{benchmark_id} config")
        terminal = True
    elif directory is not None and not_run:
        config = {"seeds": campaign["seeds"] if campaign else [],
                  "models": ["sol"], "information": ["actor-only", "perfect"],
                  "policy": benchmark_id,
                  "baseline_recipe": {"benchmark_id": benchmark_id, "policy": benchmark_id},
                  "prepared_roots_from": {
                      "result_sha256": campaign["source_result_sha256"] if campaign else None,
                      "root_hashes": campaign["root_hashes"] if campaign else None}}
    elif directory is not None:
        config_path = directory / "config.json"
        if config_path.is_file() and not config_path.is_symlink():
            config = _mapping(_read_json(config_path, label=f"{benchmark_id} row config"),
                              label=f"{benchmark_id} row config")
        elif campaign is not None:
            config = {"seeds": campaign["seeds"], "models": ["sol"],
                      "information": ["actor-only", "perfect"], "policy": benchmark_id,
                      "baseline_recipe": {"benchmark_id": benchmark_id, "policy": benchmark_id},
                      "prepared_roots_from": {
                          "result_sha256": campaign["source_result_sha256"],
                          "root_hashes": campaign["root_hashes"]}}
        else:
            raise PanelReadoutError(f"{benchmark_id}: partial row has no config.json")
    else:
        if campaign is None:
            raise PanelReadoutError(f"{benchmark_id}: not-run row needs campaign root identity")
        config = {"seeds": campaign["seeds"], "models": ["sol"],
                  "information": ["actor-only", "perfect"], "policy": benchmark_id,
                  "baseline_recipe": {"benchmark_id": benchmark_id, "policy": benchmark_id},
                  "prepared_roots_from": {
                      "result_sha256": campaign["source_result_sha256"],
                      "root_hashes": campaign["root_hashes"]}}
    seeds, source_sha, root_hashes, recipe = _validate_config(benchmark_id, config, campaign)
    if terminal:
        mirrors = report.get("mirrors")
        if not isinstance(mirrors, list):
            raise PanelReadoutError(f"{benchmark_id}: mirrors must be a list")
        report_roots = report.get("roots")
        prepared = _mapping(report.get("prepared_roots"), label=f"{benchmark_id} prepared roots")
        if (prepared.get("result_sha256") != source_sha
                or prepared.get("root_hashes") != dict(root_hashes)
                or not isinstance(report_roots, Mapping)
                or dict(report_roots) != dict(root_hashes)):
            raise PanelReadoutError(f"{benchmark_id}: report roots disagree with prepared roots")
    elif directory is not None:
        mirrors = []
        for path in sorted(directory.glob("mirror-*.json")):
            if path.is_symlink() or not path.is_file():
                raise PanelReadoutError(f"{benchmark_id}: mirror is not a regular file")
            mirrors.append(_read_json(path, label=f"{benchmark_id} mirror file"))
    else:
        mirrors = []
    expected = {f"sol-{info}-seed{seed}-flip{flip}"
                for info in INFORMATION.values() for seed in seeds for flip in (0, 1)}
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for raw in mirrors:
        row = _mapping(raw, label=f"{benchmark_id} mirror")
        key = row.get("key")
        if not isinstance(key, str) or key in seen:
            raise PanelReadoutError(f"{benchmark_id}: mirror keys are not unique")
        seen.add(key)
        if key not in expected:
            raise PanelReadoutError(f"{benchmark_id}: unexpected mirror key {key!r}")
        # Keys are producer-owned; field identities must repeat them exactly.
        if (row.get("schema") != "w32-llm-benchmark-mirror-v1"
                or row.get("arm") != f"sol-{row.get('information')}"
                or row.get("model") != "sol"
                or row.get("information") not in INFORMATION.values()
                or type(row.get("seed")) is not int
                or type(row.get("flip")) is not int or row.get("flip") not in (0, 1)
                or row.get("key") != f"sol-{row.get('information')}-seed{row.get('seed')}-flip{row.get('flip')}"
                or type(row.get("complete")) is not bool):
            raise PanelReadoutError(f"{benchmark_id}: mirror identity mismatch for {key}")
        if row["complete"] and not _number(row.get("signed_levels")):
            raise PanelReadoutError(f"{benchmark_id}: complete mirror lacks signed_levels: {key}")
        row_copy = dict(row)
        # The producer materializes all slots after a panel stop.  Only a
        # non-``not_run``/non-setup-failed row was actually attempted.
        row_copy["_attempted"] = row.get("status") not in {"not_run", "setup_failed"}
        rows.append(row_copy)
    if terminal and (seen != expected or len(rows) != MIRROR_COUNT):
        raise PanelReadoutError(f"{benchmark_id}: expected all {MIRROR_COUNT} unique attempted slots")
    if not terminal:
        for key in sorted(expected - seen):
            info = key.split("-seed", 1)[0].removeprefix("sol-")
            seed_flip = key.split("-seed", 1)[1]
            seed, flip = seed_flip.split("-flip")
            rows.append({"schema": "w32-llm-benchmark-mirror-v1", "key": key,
                         "arm": f"sol-{info}", "model": "sol", "information": info,
                         "seed": int(seed), "flip": int(flip), "complete": False,
                         "status": "not_run", "error": "mirror slot not attempted",
                         "_attempted": False})
    identity = {"benchmark_id": benchmark_id, "policy": recipe.get("policy"),
                "registered_policy": config.get("policy"),
                "directory": str(directory.resolve()) if directory is not None else None,
                "source_result_sha256": source_sha, "root_hashes": dict(root_hashes),
                "seeds": list(seeds), "terminal": terminal}
    return dict(report), rows, identity


def _arm_report(rows: Sequence[Mapping[str, object]], information: str,
                *, bootstrap_seed: int = BOOTSTRAP_SEED) -> dict[str, object]:
    selected = [row for row in rows if row.get("information") == information]
    attempted = [row for row in selected if row.get("_attempted", True) is True]
    by_seed: dict[int, dict[int, Mapping[str, object]]] = {}
    for row in selected:
        by_seed.setdefault(int(row["seed"]), {})[int(row["flip"])] = row
    values: list[float] = []
    complete_seeds: list[int] = []
    for seed in sorted(by_seed):
        pair = by_seed[seed]
        if pair.get(0, {}).get("complete") is True and pair.get(1, {}).get("complete") is True:
            # w32's signed_levels is opponent-perspective; negate exactly
            # once at the consumer boundary for policy-minus-Sol.
            values.append(-((float(pair[0]["signed_levels"]) + float(pair[1]["signed_levels"])) / 2.0))
            complete_seeds.append(seed)
    attempted_seeds = sum(
        pair.get(0, {}).get("_attempted", True) is True
        and pair.get(1, {}).get("_attempted", True) is True
        for pair in by_seed.values())
    failures = [{"key": row.get("key"), "seed": row.get("seed"), "flip": row.get("flip"),
                 "status": row.get("status"), "error": row.get("error"), "row": dict(row)}
                for row in selected if row.get("complete") is not True]
    wall = [float(row["wall_seconds"]) for row in selected if _number(row.get("wall_seconds"))]
    decision_wall = [float(event["wall_seconds"])
                     for row in selected for event in (row.get("events", []) if isinstance(row.get("events"), list) else [])
                     if isinstance(event, Mapping) and _number(event.get("wall_seconds"))]
    calls = [call for row in selected for call in (row.get("calls", []) if isinstance(row.get("calls"), list) else [])]
    token_usage = _usage(calls)
    paired = _contrast(values, seed=bootstrap_seed)
    return {"information": information, "attempted_mirrors": len(attempted),
            "expected_mirrors": len(selected), "missing_mirrors": len(selected) - len(attempted),
            "attempted_pairs": attempted_seeds, "complete_mirrors": sum(row.get("complete") is True for row in selected),
            "complete_pairs": len(values), "complete_deal_pairs": len(values),
            "complete_deal_seeds": complete_seeds,
            "failures": failures, "failure_count": len(failures),
            "paired_signed_levels": paired,
            "paired_signed_level_mean": paired["mean"],
            "deal_cluster_ci95": paired["ci95"],
            "win_rates": {"deals": _win_rates(values),
                          "mirrors": _win_rates([-float(row["signed_levels"]) for row in selected if row.get("complete") is True])},
            "latency": {"mirror_wall_seconds": _stats(wall), "decision_wall_seconds": _stats(decision_wall)},
            "tokens": token_usage,
            "transport_health": _transport_health(calls),
            "raw_cost_tokens": token_usage["total_tokens"],
            "rollout_usage": _rollout_stats(selected),
            "partial": len(values) != attempted_seeds or len(attempted) != len(selected)}


def _forfeit_arm_report(rows, information, *, bootstrap_seed=BOOTSTRAP_SEED,
                        protocol=PRESERVE_ILLEGAL):
    """Explicit alternate endpoint; never overwrite completed-only scores."""
    selected = [dict(row) for row in rows if row.get('information') == information]
    pairs, failed, unattempted, blocked = {}, 0, 0, 0
    for row in selected:
        disposition = attempt_disposition(row, protocol=protocol)
        failed += disposition == 'retained-model-failure'
        unattempted += disposition == 'unattempted'
        blocked += disposition == 'stop'
        score = None
        if disposition == 'complete':
            score = -float(row['signed_levels'])
        elif disposition == 'retained-model-failure':
            score = 1.0  # model forfeits -1; policy-minus-model negates once
        pairs.setdefault(row['seed'], {})[row['flip']] = score
    values = [(pair[0] + pair[1]) / 2 for pair in pairs.values()
              if set(pair) == {0, 1} and all(v is not None for v in pair.values())]
    return {'protocol': protocol,
            'forfeit_signed_levels_model_perspective': -1,
            'forfeit_signed_levels_policy_perspective': 1,
            'scheduled_mirrors': len(selected), 'illegal_mirrors': failed,
            'illegal_failure_rate': failed / len(selected) if selected else None,
            'unattempted_mirrors': unattempted, 'unclassified_failures': blocked,
            'scored_pairs': len(values),
            'status': 'blocked' if blocked else ('partial' if unattempted else 'complete'),
            'paired_signed_levels': None if blocked else _contrast(values, seed=bootstrap_seed)}


def _matching_values(left: Sequence[Mapping[str, object]], right: Sequence[Mapping[str, object]], information: str) -> list[float]:
    def pairs(rows: Sequence[Mapping[str, object]]) -> dict[int, float]:
        by_seed: dict[int, dict[int, Mapping[str, object]]] = {}
        for row in rows:
            if row.get("information") == information:
                by_seed.setdefault(int(row["seed"]), {})[int(row["flip"])] = row
        return {seed: -((float(pair[0]["signed_levels"]) + float(pair[1]["signed_levels"])) / 2.0)
                for seed, pair in by_seed.items()
                if pair.get(0, {}).get("complete") is True and pair.get(1, {}).get("complete") is True}
    a, b = pairs(left), pairs(right)
    return [a[seed] - b[seed] for seed in sorted(set(a) & set(b))]


def analyze_panel(row_directories: Mapping[str, str | Path | None], *, bootstrap_seed: int = BOOTSTRAP_SEED) -> dict[str, object]:
    """Validate and summarize exactly the nine authorized panel rows."""
    if set(row_directories) != set(POLICIES):
        raise PanelReadoutError("row mapping must contain exactly the nine authorized benchmark_ids")
    reports: dict[str, tuple[dict[str, object], list[dict[str, object]], dict[str, object]]] = {}
    common_source: str | None = None
    common_roots: dict[str, object] | None = None
    common_seeds: list[int] | None = None
    campaign: Mapping[str, object] | None = None
    for value in row_directories.values():
        if value is None or value == "not-run":
            continue
        campaign = _campaign_context(Path(value).expanduser())
        if campaign is not None:
            break
    for benchmark_id in POLICIES:
        value = row_directories[benchmark_id]
        not_run = value is None or value == "not-run"
        directory = None if not_run else Path(value).expanduser()
        local_campaign = _campaign_context(directory) if directory is not None else None
        report, rows, identity = _validate_row_report(
            benchmark_id, directory, campaign=local_campaign or campaign, not_run=not_run)
        if common_seeds is None:
            common_seeds = identity["seeds"]
        elif set(identity["seeds"]) != set(common_seeds):
            raise PanelReadoutError("row directories do not use the same ten seeds")
        if common_source is None:
            common_source, common_roots = identity["source_result_sha256"], identity["root_hashes"]
        elif identity["source_result_sha256"] != common_source or identity["root_hashes"] != common_roots:
            raise PanelReadoutError("row directories do not share prepared-root source SHA/root hashes")
        reports[benchmark_id] = (report, rows, identity)
    return _analyze_validated(reports, common_seeds, common_source, common_roots,
                              bootstrap_seed=bootstrap_seed)


def analyze_panel_reports(report_data, campaign_contexts, *, bootstrap_seed=BOOTSTRAP_SEED):
    """Score supplied decoded reports without ANY filesystem access.

    This validates producer shapes, not provenance. The sealed admission
    caller must authenticate bytes, terminal accounting and retention first.
    Unlike the legacy directory API, no missing/partial file fallback exists.
    """
    if (type(report_data) is not dict or set(report_data) != set(POLICIES)
            or type(campaign_contexts) is not dict or set(campaign_contexts) != set(POLICIES)):
        raise PanelReadoutError('exact nine reports and contexts required')
    reports = {}
    common = None
    for key in POLICIES:
        if type(report_data[key]) is not dict or type(campaign_contexts[key]) is not dict:
            raise PanelReadoutError('report/context must be objects')
        report, rows, identity = _validate_row_report(
            key, None, campaign=campaign_contexts[key], report_data=report_data[key])
        if identity['seeds'] != campaign_contexts[key]['seeds']:
            raise PanelReadoutError('report seed order differs from campaign')
        current = (identity['seeds'], identity['source_result_sha256'], identity['root_hashes'])
        if common is None:
            common = current
        elif current != common:
            raise PanelReadoutError('reports do not share root/schedule identity')
        reports[key] = (report, rows, identity)
    return _analyze_validated(reports, *common, bootstrap_seed=bootstrap_seed)


def analyze_stage1_reports(report_data, campaign_contexts, *, bootstrap_seed=BOOTSTRAP_SEED):
    """Analyze only authenticated, fresh feedback-ON stage-1 decoded reports.

    No filesystem access or implicit historical rows. The sealed caller owns
    provenance admission; terminal, treatment and shared-root checks live here.
    """
    from shengji.luna.benchmark_terminal import validate_scheduled_terminal

    policies = ('smv3-pv', 'm1-prior')
    if (type(report_data) is not dict or set(report_data) != set(policies)
            or type(campaign_contexts) is not dict or set(campaign_contexts) != set(policies)):
        raise PanelReadoutError('stage1 requires exactly two reports and contexts')
    reports, accounting = {}, {}
    common = None
    for key in policies:
        report = _mapping(report_data[key], label='stage1 report')
        config = _mapping(report.get('config'), label='stage1 config')
        if config.get('invalid_action_feedback') is not True:
            raise PanelReadoutError('stage1 requires explicit feedback ON')
        context = _mapping(campaign_contexts[key], label='stage1 context')
        validated = _validate_row_report(key, None, campaign=context, report_data=report)
        identity = validated[2]
        if identity['seeds'] != context['seeds']:
            raise PanelReadoutError('stage1 seed order differs from campaign')
        current = (identity['seeds'], identity['source_result_sha256'], identity['root_hashes'])
        if common is not None and current != common:
            raise PanelReadoutError('stage1 reports do not share root/schedule identity')
        common = current
        accounting[key] = validate_scheduled_terminal(report, seeds=identity['seeds'])
        reports[key] = validated
    result = _analyze_validated(reports, *common, bootstrap_seed=bootstrap_seed, policies=policies)
    result.update(schema='sol-feedback-on-stage1-readout-v1', treatment='feedback-ON',
                  terminal_accounting=accounting)
    count_keys = ('decisions_with_rejections', 'rejected_attempts',
                  'corrected_decisions', 'exhausted_decisions', 'interrupted_decisions')
    for key in policies:
        for arm, information in INFORMATION.items():
            counts = dict.fromkeys(count_keys, 0)
            for row in reports[key][1]:
                if row['information'] != information or not row['_attempted']:
                    continue
                if row.get('invalid_action_feedback') is not True:
                    raise PanelReadoutError('stage1 mirror must declare feedback ON')
                raw_counts = row.get('final_action_feedback_counts')
                if (type(raw_counts) is not dict or set(raw_counts) != set(count_keys)
                        or any(type(v) is not int or v < 0 for v in raw_counts.values())
                        or raw_counts['decisions_with_rejections'] != sum(
                            raw_counts[k] for k in ('corrected_decisions', 'exhausted_decisions',
                                                   'interrupted_decisions'))):
                    raise PanelReadoutError('stage1 feedback counters missing or inconsistent')
                for field in count_keys:
                    counts[field] += raw_counts[field]
            result['policies'][key][arm]['final_action_feedback_counts'] = counts
    return result


def _analyze_validated(reports, common_seeds, common_source, common_roots, *, bootstrap_seed,
                       policies=POLICIES):
    protocols = {key: value[0].get('config', {}).get('failure_protocol', FAIL_STOP)
                 for key, value in reports.items()}
    if any(protocol not in (FAIL_STOP, PRESERVE_ILLEGAL) for protocol in protocols.values()):
        raise PanelReadoutError('unknown failure protocol')
    amended_panel = PRESERVE_ILLEGAL in protocols.values()
    policy_rows: dict[str, object] = {}
    for benchmark_id in policies:
        report, rows, identity = reports[benchmark_id]
        sol = _arm_report(rows, INFORMATION["sol"], bootstrap_seed=bootstrap_seed)
        pt_sol = _arm_report(rows, INFORMATION["pt_sol"], bootstrap_seed=bootstrap_seed)
        policy_rows[benchmark_id] = {
            "benchmark_id": benchmark_id, "identity": identity,
            "status": "complete" if not sol["partial"] and not pt_sol["partial"] else "partial",
            "attempted_mirrors": sol["attempted_mirrors"] + pt_sol["attempted_mirrors"],
            "expected_mirrors": MIRROR_COUNT,
            "missing_mirrors": sol["missing_mirrors"] + pt_sol["missing_mirrors"],
            "complete_mirrors": sol["complete_mirrors"] + pt_sol["complete_mirrors"],
            "attempted_pairs": sol["attempted_pairs"] + pt_sol["attempted_pairs"],
            "complete_pairs": sol["complete_pairs"] + pt_sol["complete_pairs"],
            "failure_count": sol["failure_count"] + pt_sol["failure_count"],
            "sol": sol, "pt_sol": pt_sol,
            "score_sign": "negative producer signed_levels (positive policy-minus-Sol)",
        }
        protocol = protocols[benchmark_id]
        if protocol == PRESERVE_ILLEGAL:
            if (type(report['config'].get('illegal_failure_limit')) is not int
                    or report['config']['illegal_failure_limit'] != 8):
                raise PanelReadoutError('amended panel requires eight-failure stop')
        if amended_panel:
            sol['forfeit_endpoint'] = _forfeit_arm_report(rows, INFORMATION['sol'], bootstrap_seed=bootstrap_seed, protocol=protocol)
            pt_sol['forfeit_endpoint'] = _forfeit_arm_report(rows, INFORMATION['pt_sol'], bootstrap_seed=bootstrap_seed, protocol=protocol)
            policy_rows[benchmark_id]['comparison_endpoint'] = 'forfeit_endpoint'
            policy_rows[benchmark_id]['failure_protocol'] = protocol
    differences: list[dict[str, object]] = []
    for index, left_id in enumerate(policies):
        for right_id in policies[index + 1:]:
            left_rows, right_rows = reports[left_id][1], reports[right_id][1]
            differences.append({"left": left_id, "right": right_id,
                                "definition": "left policy minus right policy on matching completed deals",
                                "sol": _contrast(_matching_values(left_rows, right_rows, INFORMATION["sol"]), seed=bootstrap_seed),
                                "pt_sol": _contrast(_matching_values(left_rows, right_rows, INFORMATION["pt_sol"]), seed=bootstrap_seed)})
            if amended_panel:
                alternate = {}
                for mode, information in INFORMATION.items():
                    aligned = aligned_forfeit_values(
                        left_rows, right_rows, information,
                        left_protocol=protocols[left_id], right_protocol=protocols[right_id])
                    values = aligned.pop('values')
                    alternate[mode] = dict(aligned, paired_signed_levels=(
                        None if values is None else _contrast(values, seed=bootstrap_seed)))
                differences[-1]['forfeit_endpoint'] = dict(
                    definition='left policy minus right policy on matching scored deal pairs; model illegality forfeits one level; unattempted never imputed',
                    **alternate)
    return {"schema": PANEL_SCHEMA, "status": "complete" if all(item["status"] == "complete" for item in policy_rows.values()) else "partial",
            "panel_size": len(policies), "benchmark_ids": list(policies), "seeds": common_seeds,
            "prepared_roots": {"source_result_sha256": common_source, "root_hashes": common_roots},
            "bootstrap": {"method": "iid deal-cluster bootstrap", "seed": bootstrap_seed,
                          "replicates": BOOTSTRAP_REPLICATES, "confidence": 0.95},
            "policies": policy_rows, "row_differences": differences,
            "interpretation": "Partial results are descriptive only; no ranking, strength superiority, or equivalence claim is emitted."}


def _load_mapping(path_or_text: str) -> dict[str, str | None]:
    try:
        if path_or_text.lstrip().startswith("{"):
            value = json.loads(path_or_text)
        else:
            candidate = Path(path_or_text)
            value = _read_json(candidate, label="rows mapping") if candidate.exists() else json.loads(path_or_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PanelReadoutError("rows mapping must be a JSON object or JSON file") from exc
    mapping = _mapping(value, label="rows mapping")
    if any(not isinstance(key, str) or not isinstance(value, (str, type(None)))
           for key, value in mapping.items()):
        raise PanelReadoutError("rows mapping keys must be strings and values paths or null")
    return dict(mapping)


def main(argv: Sequence[str] | None = None) -> int:
    # This guard is independent of checkout/bundle layout. Arithmetic remains
    # importable for the sealed adapter and synthetic tests, not raw CLI reads.
    raise PanelReadoutError(
        'Panel readout forbids the directory CLI; use the reviewed sealed wrapper')


if __name__ == "__main__":
    raise SystemExit(main())

"""Pure readout for the bounded release-46 versus release-36 Sol panel.

The producer records ``signed_levels`` from the opponent's perspective.  This
reader negates those scores once, averages the two flips into deal clusters,
and compares release 46 with the frozen release-36 recipe.  The pure reader
accepts decoded terminal reports; the sealed entrypoint below only opens the
two report bytes pinned by an independently authenticated input plan.
"""
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from pathlib import Path

from shengji.luna.benchmark_failure_protocol import (
    PRESERVE_ILLEGAL, attempt_disposition,
)
from shengji.luna.benchmark_terminal import validate_scheduled_terminal
from shengji.luna.benchmark_retention import _directory, _json, _read, _regular
from scripts.production_llm_panel_readout import _contrast


SCHEMA = "sol-actor-panel-readout-v1"
REPORT_SCHEMA = "w32-llm-benchmark-v1"
POLICIES = ("smv3-pv", "release46-pv")
SEED_COUNT = 10
MIRROR_COUNT = SEED_COUNT * 2
BOOTSTRAP_SEED = 20261016
ALLOWED_CONFIG_DIFFERENCES = frozenset({"baseline_recipe", "policy", "checkpoint"})
PLAN_SCHEMA = "sol-actor-panel-readout-plan-v1"
PLAN_KEYS = frozenset({"schema", "report_refs", "expected_configs"})


class ActorPanelReadoutError(ValueError):
    """The supplied reports or expected configurations are not admissible."""


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ActorPanelReadoutError(f"{label} must be an object")
    return value


def _strict_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return (set(left) == set(right)
                and all(_strict_equal(left[key], right[key]) for key in left))
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def _hex64(value: object, *, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ActorPanelReadoutError(f"{label} must be a lowercase SHA256")
    return value


def _root_identity(config: Mapping[str, object], *, seeds: list[int], label: str):
    prepared = _mapping(config.get("prepared_roots_from"),
                        label=f"{label} prepared roots")
    source = _hex64(prepared.get("result_sha256"),
                    label=f"{label} prepared-root source")
    roots = prepared.get("root_hashes")
    if not isinstance(roots, Mapping) or set(roots) != {str(seed) for seed in seeds}:
        raise ActorPanelReadoutError(f"{label} prepared roots do not cover the seed order")
    root_hashes = {
        str(seed): _hex64(roots[str(seed)], label=f"{label} root {seed}")
        for seed in seeds
    }
    return source, root_hashes


def _validate_expected_config(policy: str, actual: Mapping[str, object],
                              expected: Mapping[str, object], *, seeds: list[int]):
    if set(actual) != set(expected):
        raise ActorPanelReadoutError(f"{policy}: report config has unexpected fields")
    if not _strict_equal(actual, expected):
        raise ActorPanelReadoutError(f"{policy}: report config differs from expected config")
    if type(actual.get("policy")) is not str or not actual.get("policy"):
        raise ActorPanelReadoutError(f"{policy}: registered policy is missing")
    checkpoint = _mapping(actual.get("checkpoint"), label=f"{policy} checkpoint")
    if type(checkpoint.get("path")) is not str or not checkpoint.get("path"):
        raise ActorPanelReadoutError(f"{policy}: checkpoint path is missing")
    _hex64(checkpoint.get("sha256"), label=f"{policy} checkpoint SHA")
    recipe = _mapping(actual.get("baseline_recipe"), label=f"{policy} recipe")
    if recipe.get("benchmark_id") != policy:
        raise ActorPanelReadoutError(f"{policy}: recipe benchmark identity differs")
    if actual.get("seeds") != seeds:
        raise ActorPanelReadoutError(f"{policy}: seed order differs from expected config")
    source, roots = _root_identity(actual, seeds=seeds, label=policy)
    return source, roots


def _report_root_identity(report: Mapping[str, object], *, source: str,
                          roots: Mapping[str, str], label: str) -> None:
    prepared = _mapping(report.get("prepared_roots"), label=f"{label} report roots")
    if (prepared.get("result_sha256") != source
            or not _strict_equal(prepared.get("root_hashes"), dict(roots))):
        raise ActorPanelReadoutError(f"{label}: report prepared roots differ")
    report_roots = report.get("roots")
    if not _strict_equal(report_roots, dict(roots)):
        raise ActorPanelReadoutError(f"{label}: report root hashes differ")


def _score_rows(report: Mapping[str, object], *, seeds: list[int], label: str):
    mirrors = report.get("mirrors")
    if not isinstance(mirrors, list):
        raise ActorPanelReadoutError(f"{label}: mirrors must be a list")
    by_seed: dict[int, dict[int, tuple[str, float | None]]] = {}
    for raw in mirrors:
        row = dict(_mapping(raw, label=f"{label} mirror"))
        disposition = attempt_disposition(row, protocol=PRESERVE_ILLEGAL)
        if disposition == "stop":
            raise ActorPanelReadoutError(f"{label}: terminal validator left an unclassified failure")
        seed, flip = row.get("seed"), row.get("flip")
        if (type(seed) is not int or seed not in seeds
                or type(flip) is not int or flip not in (0, 1)):
            raise ActorPanelReadoutError(f"{label}: mirror identity is malformed")
        if seed in by_seed and flip in by_seed[seed]:
            raise ActorPanelReadoutError(f"{label}: duplicate mirror identity")
        score: float | None = None
        if disposition == "complete":
            value = row.get("signed_levels")
            if (type(value) not in (int, float) or isinstance(value, bool)
                    or not math.isfinite(float(value))):
                raise ActorPanelReadoutError(f"{label}: complete score is not finite")
            score = -float(value)
        by_seed.setdefault(seed, {})[flip] = (disposition, score)
    if set(by_seed) != set(seeds) or any(set(pair) != {0, 1} for pair in by_seed.values()):
        raise ActorPanelReadoutError(f"{label}: terminal mirrors do not cover both flips")
    complete_seeds = []
    deal_values: dict[int, float] = {}
    failed = unattempted = 0
    complete_mirrors = 0
    failed_keys: list[str] = []
    unattempted_keys: list[str] = []
    for seed in seeds:
        pair = by_seed[seed]
        dispositions = [pair[flip][0] for flip in (0, 1)]
        failed += sum(disposition == "retained-model-failure" for disposition in dispositions)
        unattempted += sum(disposition == "unattempted" for disposition in dispositions)
        complete_mirrors += sum(disposition == "complete" for disposition in dispositions)
        failed_keys.extend(
            f"sol-actor-only-seed{seed}-flip{flip}"
            for flip in (0, 1) if pair[flip][0] == "retained-model-failure")
        unattempted_keys.extend(
            f"sol-actor-only-seed{seed}-flip{flip}"
            for flip in (0, 1) if pair[flip][0] == "unattempted")
        if all(disposition == "complete" for disposition in dispositions):
            deal_values[seed] = sum(pair[flip][1] for flip in (0, 1)) / 2.0
            complete_seeds.append(seed)
    return by_seed, deal_values, {
        "scheduled_mirrors": MIRROR_COUNT,
        "complete_mirrors": complete_mirrors,
        "failed_mirrors": failed,
        "unattempted_mirrors": unattempted,
        "failed_keys": failed_keys,
        "unattempted_keys": unattempted_keys,
        "complete_deal_count": len(complete_seeds),
        "complete_deal_seeds": complete_seeds,
        "partial": complete_mirrors != MIRROR_COUNT,
    }


def _policy_summary(policy: str, report: Mapping[str, object], *, seeds: list[int],
                    source: str, roots: Mapping[str, str], accounting: Mapping[str, object],
                    bootstrap_seed: int):
    _, deal_values, coverage = _score_rows(report, seeds=seeds, label=policy)
    return {
        "policy": policy,
        "status": "complete" if not coverage["partial"] else "partial",
        "coverage": coverage,
        "deal_values": [deal_values[seed] for seed in coverage["complete_deal_seeds"]],
        "deal_mean": _contrast(
            [deal_values[seed] for seed in coverage["complete_deal_seeds"]],
            seed=bootstrap_seed),
        "terminal_accounting": dict(accounting),
        "prepared_roots": {"source_result_sha256": source, "root_hashes": dict(roots)},
    }, deal_values


def analyze_actor_panel_reports(report_data: Mapping[str, object],
                                expected_configs: Mapping[str, object], *,
                                bootstrap_seed: int = BOOTSTRAP_SEED) -> dict[str, object]:
    """Validate and summarize exactly two terminal actor-only reports.

    ``expected_configs`` is an explicit producer contract supplied by the
    sealed caller.  Each report must equal its own expected config exactly;
    only recipe, registered policy, and checkpoint fields may differ between
    the two policy configs.
    """
    if (not isinstance(report_data, Mapping) or set(report_data) != set(POLICIES)
            or not isinstance(expected_configs, Mapping)
            or set(expected_configs) != set(POLICIES)):
        raise ActorPanelReadoutError("exact release46-pv and smv3-pv reports/configs are required")
    expected_seed_values = []
    for policy in POLICIES:
        expected = _mapping(expected_configs[policy], label=f"{policy} expected config")
        seeds = expected.get("seeds")
        if (not isinstance(seeds, list) or len(seeds) != SEED_COUNT
                or any(type(seed) is not int or isinstance(seed, bool) for seed in seeds)
                or len(set(seeds)) != SEED_COUNT):
            raise ActorPanelReadoutError(f"{policy}: expected config needs ten ordered seeds")
        expected_seed_values.append(list(seeds))
    if expected_seed_values[0] != expected_seed_values[1]:
        raise ActorPanelReadoutError("expected configs do not share the ordered seed list")
    seeds = expected_seed_values[0]

    reports = {}
    summaries = {}
    common_source = common_roots = None
    common_config = None
    for policy in POLICIES:
        report = _mapping(report_data[policy], label=f"{policy} report")
        if report.get("schema") != REPORT_SCHEMA or report.get("mode") != "run":
            raise ActorPanelReadoutError(f"{policy}: report is not a terminal benchmark run")
        config = _mapping(report.get("config"), label=f"{policy} config")
        source, roots = _validate_expected_config(
            policy, config, _mapping(expected_configs[policy], label=f"{policy} expected config"),
            seeds=seeds)
        if common_config is None:
            common_config = config
        else:
            for key in set(common_config) | set(config):
                if key in ALLOWED_CONFIG_DIFFERENCES:
                    continue
                if not _strict_equal(common_config.get(key), config.get(key)):
                    raise ActorPanelReadoutError(f"{policy}: Sol configuration differs for {key!r}")
        if common_source is None:
            common_source, common_roots = source, roots
        elif source != common_source or roots != common_roots:
            raise ActorPanelReadoutError(f"{policy}: prepared roots differ")
        try:
            accounting = validate_scheduled_terminal(
                report, seeds=seeds, failure_limit=8,
                information_modes=("actor-only",))
        except (TypeError, ValueError) as exc:
            raise ActorPanelReadoutError(f"{policy}: terminal validation failed") from exc
        reports[policy] = report
        _report_root_identity(report, source=source, roots=roots, label=policy)
        summaries[policy], _ = _policy_summary(
            policy, report, seeds=seeds, source=source, roots=roots,
            accounting=accounting, bootstrap_seed=bootstrap_seed)

    values = {}
    for policy in POLICIES:
        _, values[policy], _ = _score_rows(reports[policy], seeds=seeds, label=policy)
    matched = [seed for seed in seeds if seed in values[POLICIES[0]] and seed in values[POLICIES[1]]]
    deltas = [values["release46-pv"][seed] - values["smv3-pv"][seed] for seed in matched]
    paired = _contrast(deltas, seed=bootstrap_seed)
    clean = all(not summaries[policy]["coverage"]["partial"]
                and summaries[policy]["coverage"]["failed_mirrors"] == 0
                and summaries[policy]["coverage"]["unattempted_mirrors"] == 0
                for policy in POLICIES)
    lower = paired["ci95"][0] if paired["ci95"] is not None else None
    upper = paired["ci95"][1] if paired["ci95"] is not None else None
    classification = ("POSITIVE" if clean and lower is not None and lower > 0 else
                      "NEGATIVE" if clean and upper is not None and upper < 0 else
                      "INCONCLUSIVE" if clean else "PARTIAL")
    comparison = {
        "left": "release46-pv", "right": "smv3-pv",
        "definition": "release46-pv minus smv3-pv on matching complete deal clusters",
        "complete_deal_seeds": matched,
        "paired_delta": paired,
        "mean": paired["mean"], "ci95": paired["ci95"],
        "classification": classification,
        "clean_complete_coverage": clean,
    }
    return {
        "schema": SCHEMA,
        "status": "complete" if clean else "partial",
        "policies": summaries,
        "seeds": list(seeds),
        "prepared_roots": {"source_result_sha256": common_source,
                           "root_hashes": dict(common_roots)},
        "comparison": comparison,
        "terminal_accounting": {
            policy: summaries[policy]["terminal_accounting"] for policy in POLICIES},
        "interpretation": (
            "Positive transfer requires complete clean coverage and a 95% deal-cluster CI lower bound above zero; "
            "partial results are descriptive only."),
    }


def _sealed_path(value: object, *, label: str) -> Path:
    """Validate a sealed artifact path without opening its contents."""
    if not isinstance(value, (str, Path)):
        raise ActorPanelReadoutError(f"{label} path must be a string")
    path = Path(value)
    if not path.is_absolute() or any(component in (".", "..")
                                    for component in path.parts):
        raise ActorPanelReadoutError(
            f"{label} path must be absolute without traversal")
    try:
        _directory(path.parent, f"{label} parent")
        # lstat-based validation is intentionally done before any report is
        # opened.  _read repeats it at the trust boundary.
        _regular(path, label)
    except Exception as exc:
        if isinstance(exc, ActorPanelReadoutError):
            raise
        raise ActorPanelReadoutError(str(exc)) from exc
    return path


def _sealed_plan(plan_path: object, expected_sha256: object):
    """Authenticate the plan and all report metadata before reading reports."""
    plan = _sealed_path(plan_path, label="readout plan")
    if type(expected_sha256) is not str:
        raise ActorPanelReadoutError("plan SHA256 must be a lowercase SHA256")
    try:
        plan_sha256 = _hex64(expected_sha256, label="plan SHA256")
        raw, actual_sha256 = _read(plan, "readout plan")
        if actual_sha256 != plan_sha256:
            raise ActorPanelReadoutError("readout plan SHA256 differs from its pin")
        value = _json(raw, "readout plan")
    except ActorPanelReadoutError:
        raise
    except Exception as exc:
        raise ActorPanelReadoutError(str(exc)) from exc
    if (not isinstance(value, Mapping)
            or set(value) != PLAN_KEYS
            or value.get("schema") != PLAN_SCHEMA):
        raise ActorPanelReadoutError("invalid actor-panel readout plan")

    refs = value.get("report_refs")
    expected_configs = value.get("expected_configs")
    if (not isinstance(refs, Mapping) or set(refs) != set(POLICIES)
            or not isinstance(expected_configs, Mapping)
            or set(expected_configs) != set(POLICIES)):
        raise ActorPanelReadoutError(
            "exact smv3-pv and release46-pv report refs/configs are required")

    validated_configs: dict[str, Mapping[str, object]] = {}
    ordered_seeds: list[int] | None = None
    for policy in POLICIES:
        expected = _mapping(expected_configs[policy], label=f"{policy} expected config")
        seeds = expected.get("seeds")
        if (not isinstance(seeds, list) or len(seeds) != SEED_COUNT
                or any(type(seed) is not int or isinstance(seed, bool) for seed in seeds)
                or len(set(seeds)) != SEED_COUNT):
            raise ActorPanelReadoutError(f"{policy}: expected config needs ten ordered seeds")
        if ordered_seeds is None:
            ordered_seeds = list(seeds)
        elif list(seeds) != ordered_seeds:
            raise ActorPanelReadoutError("expected configs do not share the ordered seed list")
        # Comparing the expected config to itself validates its independently
        # supplied shape without consulting either report.
        _validate_expected_config(policy, expected, expected, seeds=ordered_seeds)
        validated_configs[policy] = expected
    first_config = validated_configs[POLICIES[0]]
    for policy in POLICIES[1:]:
        other = validated_configs[policy]
        for key in set(first_config) | set(other):
            if key in ALLOWED_CONFIG_DIFFERENCES:
                continue
            if not _strict_equal(first_config.get(key), other.get(key)):
                raise ActorPanelReadoutError(f"{policy}: expected Sol configuration differs for {key!r}")

    # Validate every reference and every expected config before opening either
    # report.  In particular, a malformed second ref cannot leave the first
    # report read as a side effect.
    paths: dict[str, Path] = {}
    normalized_refs: dict[str, tuple[Path, str]] = {}
    for policy in POLICIES:
        ref = refs[policy]
        if not isinstance(ref, Mapping) or set(ref) != {"path", "sha256"}:
            raise ActorPanelReadoutError(f"{policy}: invalid report reference")
        try:
            digest = _hex64(ref["sha256"], label=f"{policy} report SHA256")
        except ActorPanelReadoutError:
            raise
        paths[policy] = _sealed_path(ref["path"], label=f"{policy} report")
        # Keep the normalized pin separate from the untrusted mapping.  This
        # also makes it impossible for later code to derive a pin from bytes.
        normalized_refs[policy] = (paths[policy], digest)
    if paths[POLICIES[0]] == paths[POLICIES[1]]:
        raise ActorPanelReadoutError("policy reports must be distinct files")

    reports: dict[str, Mapping[str, object]] = {}
    for policy in POLICIES:
        path, pinned_sha256 = normalized_refs[policy]
        try:
            report_raw, actual_sha256 = _read(path, f"{policy} sealed report")
            if actual_sha256 != pinned_sha256:
                raise ActorPanelReadoutError(
                    f"{policy}: report SHA256 differs from its pin")
            report = _json(report_raw, f"{policy} sealed report")
        except ActorPanelReadoutError:
            raise
        except Exception as exc:
            raise ActorPanelReadoutError(str(exc)) from exc
        if not isinstance(report, Mapping):
            raise ActorPanelReadoutError(f"{policy}: sealed report must be an object")
        reports[policy] = report
    result = analyze_actor_panel_reports(reports, validated_configs)
    result["seals"] = {
        "plan_sha256": plan_sha256,
        "report_refs": {
            policy: {"path": str(paths[policy]),
                     "sha256": normalized_refs[policy][1]}
            for policy in POLICIES
        },
        "metadata_and_content_validated": True,
    }
    return result


def read_sealed_actor_panel(plan_path: str | Path,
                            expected_sha256: str) -> dict[str, object]:
    """Read exactly the two report bytes pinned by an external plan."""
    return _sealed_plan(plan_path, expected_sha256)


def main(argv=None):
    if argv is not None and "--reports" in argv:
        raise ActorPanelReadoutError(
            "decoded reports/raw disk access is not a sealed plan; use --plan and --plan-sha256")
    parser = argparse.ArgumentParser(prog="sol_actor_panel_readout")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args(argv)
    result = read_sealed_actor_panel(args.plan, args.plan_sha256)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = ["ActorPanelReadoutError", "BOOTSTRAP_SEED", "PLAN_SCHEMA", "POLICIES",
           "SCHEMA", "analyze_actor_panel_reports", "read_sealed_actor_panel"]


if __name__ == "__main__":
    raise SystemExit(main())

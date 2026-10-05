"""Fail-closed terminal validation for the bounded Sol schedule."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .benchmark_failure_protocol import (PRESERVE_ILLEGAL,
                                         attempt_disposition,
                                         summarize_scheduled)


SCHEMA = "w32-llm-benchmark-v1"
MIRROR_SCHEMA = "w32-llm-benchmark-mirror-v1"
SCHEDULED = 40


def _strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (set(left) == set(right)
                and all(_strict_equal(left[key], right[key]) for key in left))
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def _seeds(value: object) -> list[int]:
    if (type(value) is not list or len(value) != 10
            or any(type(seed) is not int or isinstance(seed, bool) for seed in value)
            or len(set(value)) != len(value)):
        raise ValueError("terminal validation requires ten unique integer seeds")
    return list(value)


def _validate_row(row: object, *, key: str, seed: int, mode: str,
                  flip: int) -> str:
    if type(row) is not dict:
        raise ValueError("terminal mirror row must be an object")
    if (row.get("schema") != MIRROR_SCHEMA
            or row.get("key") != key
            or row.get("arm") != f"sol-{mode}"
            or row.get("model") != "sol"
            or row.get("information") != mode
            or type(row.get("seed")) is not int
            or isinstance(row.get("seed"), bool)
            or row.get("seed") != seed
            or type(row.get("flip")) is not int
            or isinstance(row.get("flip"), bool)
            or row.get("flip") != flip):
        raise ValueError(f"terminal mirror identity drift for {key}")
    disposition = attempt_disposition(row, protocol=PRESERVE_ILLEGAL)
    if disposition == "complete":
        score = row.get("signed_levels")
        if (type(score) not in (int, float) or isinstance(score, bool)
                or not math.isfinite(score)
                or "error" in row or "failure" in row):
            raise ValueError(f"complete mirror {key} has invalid score/failure")
        return disposition
    if disposition == "retained-model-failure":
        if "signed_levels" in row:
            raise ValueError(f"failed mirror {key} carries a gameplay score")
        return disposition
    if disposition == "unattempted":
        if ("failure" in row or "signed_levels" in row
                or row.get("calls", []) != [] or row.get("events", []) != []):
            raise ValueError(f"pending mirror {key} carries attempted data")
        return disposition
    raise ValueError(f"terminal mirror {key} has an unknown failure")


def validate_scheduled_terminal(
        report: Mapping[str, Any], *, seeds: Sequence[int],
        failure_limit: int = 8,
        retention_binding: Mapping[str, str] | None = None) -> dict[str, int | str]:
    """Validate one immutable, complete-or-bounded terminal Sol report."""
    if type(report) is not dict:
        raise ValueError("terminal report must be an object")
    if type(failure_limit) is not int or isinstance(failure_limit, bool) \
            or failure_limit != 8:
        raise ValueError("terminal validation requires failure limit 8")
    expected_seeds = _seeds(list(seeds) if not isinstance(seeds, list) else seeds)
    if (report.get("schema") != SCHEMA or report.get("mode") != "run"):
        raise ValueError("report is not a benchmark run")
    config = report.get("config")
    if type(config) is not dict:
        raise ValueError("terminal report config is missing")
    binding = config.get('retained_attempts')
    if retention_binding is None:
        if binding is not None:
            raise ValueError('retention not authorized for this row')
    elif (type(binding) is not dict
          or set(retention_binding) != {'source', 'result_sha256', 'plan_sha256'}
          or any(not value or binding.get(key) != value
                 for key, value in retention_binding.items())):
        raise ValueError('retention does not match launcher binding')
    if (config.get("failure_protocol") != PRESERVE_ILLEGAL
            or not _strict_equal(config.get("illegal_failure_limit"), failure_limit)
            or config.get("models") != ["sol"]
            or config.get("information") != ["actor-only", "perfect"]
            or not _strict_equal(config.get("seeds"), expected_seeds)):
        raise ValueError("terminal report schedule configuration drift")
    mirrors = report.get("mirrors")
    if type(mirrors) is not list or len(mirrors) != SCHEDULED:
        raise ValueError("terminal report must contain exactly forty mirrors")
    expected_keys = {
        f"sol-{mode}-seed{seed}-flip{flip}"
        for mode in ("actor-only", "perfect")
        for seed in expected_seeds for flip in (0, 1)}
    rows: dict[str, dict[str, Any]] = {}
    for row in mirrors:
        if type(row) is not dict or type(row.get("key")) is not str:
            raise ValueError("terminal mirror key is malformed")
        key = row["key"]
        if key in rows or key not in expected_keys:
            raise ValueError("terminal mirror keys are not the exact schedule")
        rows[key] = row
    if set(rows) != expected_keys:
        raise ValueError("terminal report has missing scheduled mirrors")

    dispositions: list[str] = []
    ordered_rows: list[dict] = []
    for mode in ("actor-only", "perfect"):
        for seed in expected_seeds:
            for flip in (0, 1):
                key = f"sol-{mode}-seed{seed}-flip{flip}"
                dispositions.append(_validate_row(
                    rows[key], key=key, seed=seed, mode=mode, flip=flip))
                ordered_rows.append(rows[key])
    # Retained terminal attempts predate this execution, even when their slot
    # occurs later in schedule order. Their failures consume the budget before
    # the first new dispatch, exactly as in the runner.
    retained = []
    for row, disposition in zip(ordered_rows, dispositions):
        lineage = row.get('lineage')
        if lineage is None:
            retained.append(False)
            continue
        binding = config.get('retained_attempts')
        if (type(lineage) is not dict or type(binding) is not dict
                or lineage.get('kind') != 'retained-terminal-attempt'
                or disposition not in ('complete', 'retained-model-failure')
                or not binding.get('source') or not binding.get('result_sha256')
                or not binding.get('plan_sha256')
                or lineage.get('source') != binding['source']
                or lineage.get('source_result_sha256') != binding['result_sha256']
                or lineage.get('retention_plan_sha256') != binding['plan_sha256']):
            raise ValueError('retained terminal lineage is not bound')
        retained.append(True)
    running_failures = sum(old and kind == 'retained-model-failure'
                           for old, kind in zip(retained, dispositions))
    for old, kind in zip(retained, dispositions):
        if old:
            continue
        if running_failures >= failure_limit and kind != 'unattempted':
            raise ValueError('new attempt after failure limit')
        if running_failures < failure_limit and kind == 'unattempted':
            raise ValueError('pending mirror before failure limit')
        running_failures += kind == 'retained-model-failure'
    try:
        recomputed = summarize_scheduled(
            list(rows.values()), failure_limit=failure_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("terminal scheduled summary cannot be recomputed") from exc
    if ("scheduled_summary" not in report
            or not _strict_equal(report["scheduled_summary"], recomputed)):
        raise ValueError("terminal scheduled summary is not authenticated")
    failed = dispositions.count("retained-model-failure")
    unattempted = dispositions.count("unattempted")
    completed = dispositions.count("complete")
    if failed > failure_limit:
        raise ValueError("terminal report exceeds failure limit")
    if failed < failure_limit and unattempted:
        raise ValueError("terminal report has pending mirrors below failure limit")
    return {"status": ("failure-limit" if failed == failure_limit
                        else "scheduled-terminal"),
            "completed": completed, "failed": failed,
            "unattempted": unattempted, "scheduled": SCHEDULED}


__all__ = ["validate_scheduled_terminal"]

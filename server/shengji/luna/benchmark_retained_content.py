"""Fail-closed validation of content retained into a recovery report."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .benchmark_failure_protocol import PRESERVE_ILLEGAL, attempt_disposition
from .benchmark_retention import _row_cost, _strict_equal
from .benchmark_terminal import validate_scheduled_terminal


_AUTH_KEYS = {
    "path", "result_sha256", "plan_sha256", "rows", "source_rows",
    "prior_cost_tokens",
}
_SOURCE_ROW_KEYS = {"row", "path", "sha256"}
_RETAINED_KEYS = {
    "plan", "plan_sha256", "source", "result_sha256", "prior_cost_tokens",
}
_LINEAGE_KEYS = {
    "source", "source_result_sha256", "source_row", "source_row_sha256",
    "kind", "retention_plan_sha256",
}
_MODES = ("actor-only", "perfect")


def _digest(value: Any, label: str) -> None:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{label} must be a lowercase SHA256")


def _auth_schedule(authenticated_retention: Mapping[str, Any]) -> set[str]:
    """Check the loader result shape and return its exact retained schedule."""
    if type(authenticated_retention) is not dict:
        raise ValueError("authenticated retention must be an object")
    if set(authenticated_retention) != _AUTH_KEYS:
        raise ValueError("authenticated retention fields are not exact")
    source = authenticated_retention["path"]
    if (type(source) is not str or not Path(source).is_absolute()
            or any(part in (".", "..") for part in Path(source).parts)):
        raise ValueError("authenticated retention source is not absolute")
    _digest(authenticated_retention["result_sha256"], "result_sha256")
    _digest(authenticated_retention["plan_sha256"], "plan_sha256")
    prior_cost = authenticated_retention["prior_cost_tokens"]
    if type(prior_cost) is not int or isinstance(prior_cost, bool) or prior_cost < 0:
        raise ValueError("authenticated prior cost is invalid")
    rows = authenticated_retention["rows"]
    source_rows = authenticated_retention["source_rows"]
    if type(rows) is not dict or type(source_rows) is not dict:
        raise ValueError("authenticated retention rows are not objects")
    if set(rows) != set(source_rows) or len(rows) != 40:
        raise ValueError("authenticated retention does not cover the exact schedule")
    seeds: set[int] = set()
    expected: set[str] = set()
    for key, row in rows.items():
        if type(key) is not str or type(row) is not dict or row.get("key") != key:
            raise ValueError("authenticated retained row identity drift")
        source_row = source_rows[key]
        if (type(source_row) is not dict
                or set(source_row) != _SOURCE_ROW_KEYS
                or type(source_row["row"]) is not dict
                or type(source_row["path"]) is not str):
            raise ValueError("authenticated source row is malformed")
        _digest(source_row["sha256"], "source row sha256")
        if source_row["row"].get("key") != key:
            raise ValueError("authenticated source row identity drift")
        matched = None
        for mode in _MODES:
            prefix = f"sol-{mode}-seed"
            if key.startswith(prefix):
                rest = key[len(prefix):]
                if "-flip" in rest:
                    seed_text, flip_text = rest.split("-flip", 1)
                    if (seed_text and flip_text in ("0", "1")
                            and seed_text == str(int(seed_text))):
                        matched = (mode, int(seed_text), int(flip_text))
                break
        if matched is None:
            raise ValueError("authenticated schedule key is malformed")
        mode, seed, flip = matched
        expected.add(f"sol-{mode}-seed{seed}-flip{flip}")
        seeds.add(seed)
    if expected != set(rows) or len(seeds) != 10:
        raise ValueError("authenticated retention is not a ten-seed schedule")
    expected_keys = {
        f"sol-{mode}-seed{seed}-flip{flip}"
        for mode in _MODES for seed in seeds for flip in (0, 1)
    }
    if expected != expected_keys:
        raise ValueError("authenticated retention has missing schedule keys")
    return expected


def _retained_binding(report: dict[str, Any], auth: Mapping[str, Any]) -> dict[str, Any] | None:
    config = report.get("config")
    if type(config) is not dict:
        raise ValueError("retained report config is missing")
    binding = config.get("retained_attempts")
    top_level = report.get("retained_attempts")
    if binding is None:
        if top_level is not None:
            raise ValueError("top-level retained attempts are not bound")
        return None
    if type(binding) is not dict or set(binding) != _RETAINED_KEYS:
        raise ValueError("retained config fields are not exact")
    if top_level is None or not _strict_equal(top_level, binding):
        raise ValueError("top-level retained attempts disagree with config")
    plan = binding["plan"]
    if (type(plan) is not str or not Path(plan).is_absolute()
            or any(part in (".", "..") for part in Path(plan).parts)):
        raise ValueError("retention plan is not an absolute path")
    if (binding["source"] != auth["path"]
            or binding["result_sha256"] != auth["result_sha256"]
            or binding["plan_sha256"] != auth["plan_sha256"]
            or binding["prior_cost_tokens"] != auth["prior_cost_tokens"]):
        raise ValueError("retained config does not match authenticated retention")
    _digest(binding["result_sha256"], "retained result_sha256")
    _digest(binding["plan_sha256"], "retained plan_sha256")
    if type(binding["source"]) is not str or type(binding["prior_cost_tokens"]) is not int:
        raise ValueError("retained config binding has invalid types")
    if isinstance(binding["prior_cost_tokens"], bool) or binding["prior_cost_tokens"] < 0:
        raise ValueError("retained prior cost is invalid")
    return binding


def validate_retained_lineage(
        report: dict[str, Any],
        authenticated_retention: Mapping[str, Any] | None) -> dict[str, int | str] | None:
    """Audit inherited content, including in a failed recovery report.

    The caller authenticates the report and supplies the historical loader's
    result. This verifies exact inherited rows and their lineage, NOT new-row
    dispositions, summary, costs or terminality. It grants no retry or scoring
    authority. Unbound reports return None, not a successful lineage audit.
    """
    if type(report) is not dict:
        raise ValueError("retained report must be an object")
    config = report.get("config")
    if type(config) is not dict:
        raise ValueError("retained report config is missing")
    if config.get("retained_attempts") is None:
        if report.get("retained_attempts") is not None:
            raise ValueError("top-level retained attempts are not bound")
        return None
    if authenticated_retention is None:
        raise ValueError("retained report lacks authenticated retention")
    auth_keys = _auth_schedule(authenticated_retention)
    binding = _retained_binding(report, authenticated_retention)
    assert binding is not None
    seeds = config.get("seeds")
    if (type(seeds) is not list
            or len(seeds) != 10
            or any(type(seed) is not int or isinstance(seed, bool) for seed in seeds)
            or set(seeds) != {
                int(key.split("-seed", 1)[1].split("-flip", 1)[0])
                for key in auth_keys
            }):
        raise ValueError("retained report seeds do not match authenticated retention")
    mirrors = report.get("mirrors")
    if type(mirrors) is not list or len(mirrors) != len(auth_keys):
        raise ValueError("retained report must contain exact schedule")
    report_rows = {}
    for row in mirrors:
        if type(row) is not dict or type(row.get("key")) is not str:
            raise ValueError("retained report row is malformed")
        key = row["key"]
        if key not in auth_keys or key in report_rows:
            raise ValueError("retained report keys are not the exact schedule")
        original = authenticated_retention["rows"][key]
        for field in ("schema", "arm", "model", "information", "seed", "flip"):
            if field not in row or not _strict_equal(row[field], original[field]):
                raise ValueError(f"retained report identity drift for {key}")
        report_rows[key] = row
    auth_rows = authenticated_retention["rows"]
    source_rows = authenticated_retention["source_rows"]
    retained_count = 0
    for key in auth_keys:
        original = auth_rows[key]
        disposition = attempt_disposition(original, protocol=PRESERVE_ILLEGAL)
        current = report_rows[key]
        lineage = current.get("lineage")
        if disposition in ("complete", "retained-model-failure"):
            retained_count += 1
            expected_lineage = {
                "source": authenticated_retention["path"],
                "source_result_sha256": authenticated_retention["result_sha256"],
                "source_row": source_rows[key]["path"],
                "source_row_sha256": source_rows[key]["sha256"],
                "kind": "retained-terminal-attempt",
                "retention_plan_sha256": authenticated_retention["plan_sha256"],
            }
            if not _strict_equal(lineage, expected_lineage):
                raise ValueError(f"retained lineage mismatch for {key}")
            without_lineage = dict(current)
            del without_lineage["lineage"]
            if not _strict_equal(without_lineage, original):
                raise ValueError(f"retained attempt content changed for {key}")
        elif disposition == "unattempted":
            if "lineage" in current:
                raise ValueError(f"new attempt {key} carries retained lineage")
        else:
            raise ValueError(f"authenticated retained row {key} has unknown disposition")
    return {"status": "retained-lineage-verified", "retained": retained_count,
            "new_slots": len(auth_keys) - retained_count}


def audit_retained_costs(
        report: dict[str, Any],
        authenticated_retention: Mapping[str, Any] | None) -> dict[str, int | str] | None:
    """Reconcile recorded usage without accepting a failed recovery report.

    Call after authenticating report bytes. Inherited rows are verified first,
    then counted once, not added again to the source total. New failed calls
    count too. This checks recorded token arithmetic, not provider billing or
    completeness of external call evidence. It does not classify or retry.
    """
    if validate_retained_lineage(report, authenticated_retention) is None:
        return None
    assert authenticated_retention is not None
    old_tokens = new_tokens = 0
    for row in report["mirrors"]:
        tokens = _row_cost(row)
        if "lineage" in row:
            old_tokens += tokens
        else:
            new_tokens += tokens
    if old_tokens != authenticated_retention["prior_cost_tokens"]:
        raise ValueError("inherited token sum disagrees with authenticated source")
    expected = {"tokens": new_tokens, "new_tokens": new_tokens,
                "prior_tokens": old_tokens, "combined_tokens": old_tokens + new_tokens}
    budget = report.get("budget")
    if type(budget) is not dict:
        raise ValueError("retained cost audit requires recorded budget")
    for key, value in expected.items():
        if type(budget.get(key)) is not int or budget[key] != value:
            raise ValueError(f"recorded budget {key} disagrees with mirror usage")
    return {"status": "retained-recorded-costs-verified", **expected}


def validate_retained_content(
        report: dict[str, Any],
        authenticated_retention: Mapping[str, Any] | None) -> dict[str, int | str] | None:
    """Verify inherited content AND ordinary terminal acceptance."""
    if validate_retained_lineage(report, authenticated_retention) is None:
        return None
    assert authenticated_retention is not None
    return validate_scheduled_terminal(
        report, seeds=report["config"]["seeds"],
        retention_binding={
            "source": authenticated_retention["path"],
            "result_sha256": authenticated_retention["result_sha256"],
            "plan_sha256": authenticated_retention["plan_sha256"],
        })


__all__ = ["validate_retained_content", "validate_retained_lineage", "audit_retained_costs"]

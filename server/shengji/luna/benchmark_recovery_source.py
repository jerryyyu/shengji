"""Authenticate a bounded Sol recovery report without accepting it.

This reader authenticates the report bytes and its forty mirror sidecars, then
audits inherited lineage and recorded costs.  It deliberately does not
classify a new failure, validate terminality, or produce runner-compatible
retained input.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from .benchmark_retained_content import audit_retained_costs, validate_retained_lineage
from .benchmark_retention import (
    REPORT_SCHEMA,
    RetentionRefusal,
    _compare_config,
    _directory,
    _hex,
    _json,
    _read,
    _strict_equal,
)


MIRROR_SCHEMA = "w32-llm-benchmark-mirror-v1"


def _reject_aliases(report: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    # The runner's retained_attempts binding is the sole accepted retention
    # spelling.  Other names must not become an unreviewed source of authority.
    for key in ("retention", "retention_plan"):
        if key in report or key in config:
            raise RetentionRefusal(f"alternative {key} binding is refused")


def _report_rows(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    mirrors = report.get("mirrors")
    if type(mirrors) is not list or len(mirrors) != 40:
        raise RetentionRefusal("recovery report must contain exactly forty mirrors")
    rows: dict[str, dict[str, Any]] = {}
    for row in mirrors:
        if type(row) is not dict or type(row.get("key")) is not str:
            raise RetentionRefusal("recovery mirror row is malformed")
        key = row["key"]
        if key in rows:
            raise RetentionRefusal("recovery mirror keys are not unique")
        rows[key] = row
    return rows


def _sidecar_names(source_directory: Path) -> set[str]:
    try:
        entries = source_directory.iterdir()
        return {
            entry.name for entry in entries
            if entry.name.startswith("mirror-") and entry.name.endswith(".json")
        }
    except OSError as exc:
        raise RetentionRefusal("cannot inspect recovery source directory") from exc


def load_recovery_source(
        source_directory: str | Path,
        result_sha256: str,
        *,
        expected_config: Mapping[str, Any],
        authenticated_retention: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Authenticate one failed recovery report and its exact mirror sidecars.

    The returned object is an audit record, not a continuation or retained
    runner input.  In particular, new failures are preserved without
    reclassification in ``report`` and are not assigned a disposition here.
    """
    supplied_result_sha = _hex(result_sha256, "result SHA256")
    if not isinstance(expected_config, Mapping):
        raise RetentionRefusal("expected_config must be an object")
    source_dir = Path(source_directory)
    _directory(source_dir, "source_directory")

    result_raw, actual_result_sha = _read(source_dir / "result.json", "result.json")
    if actual_result_sha != supplied_result_sha:
        raise RetentionRefusal("result SHA256 mismatch")
    report = _json(result_raw, "result.json")
    if (type(report) is not dict
            or report.get("schema") != REPORT_SCHEMA
            or report.get("mode") != "run"):
        raise RetentionRefusal("source is not a benchmark run report")
    if report.get("prior") not in (None, {}):
        raise RetentionRefusal("continuation chains are refused")
    config = report.get("config")
    if type(config) is not dict:
        raise RetentionRefusal("recovery report config is missing")
    _reject_aliases(report, config)

    # Compare the source recipe and roots against the caller's expected
    # configuration while removing only the explicitly audited binding.
    config_for_compare = copy.deepcopy(config)
    config_for_compare.pop("retained_attempts", None)
    _compare_config(config_for_compare, expected_config)

    # This both requires an authenticated retained binding and verifies the
    # exact inherited schedule/content.  It intentionally does not classify
    # or accept the new portion of the report.
    lineage = validate_retained_lineage(report, authenticated_retention)
    if lineage is None:
        raise RetentionRefusal("recovery report lacks authenticated retention binding")

    rows = _report_rows(report)
    expected_names = {
        f"mirror-{row['model']}-{row['information']}-{row['seed']}-{row['flip']}.json"
        for row in rows.values()
    }
    actual_names = _sidecar_names(source_dir)
    if actual_names != expected_names:
        raise RetentionRefusal("recovery source does not contain the exact mirror sidecars")

    source_rows: dict[str, dict[str, Any]] = {}
    for key, row in rows.items():
        mirror_path = source_dir / (
            f"mirror-{row['model']}-{row['information']}-{row['seed']}-{row['flip']}.json")
        mirror_raw, mirror_sha = _read(mirror_path, f"mirror {key}")
        mirror_obj = _json(mirror_raw, f"mirror {key}")
        if type(mirror_obj) is not dict or not _strict_equal(mirror_obj, row):
            raise RetentionRefusal(f"mirror {key} disagrees with report")
        if mirror_obj.get("schema") != MIRROR_SCHEMA:
            raise RetentionRefusal(f"mirror {key} has an invalid schema")
        source_rows[key] = {
            "row": copy.deepcopy(mirror_obj),
            "path": str(mirror_path),
            "sha256": mirror_sha,
        }

    costs = audit_retained_costs(report, authenticated_retention)
    if costs is None:
        raise RetentionRefusal("recovery report lacks authenticated cost audit")

    return {
        "report": report,
        "path": str(source_dir),
        "result_sha256": supplied_result_sha,
        "source_pins": {"path": str(source_dir), "result_sha256": supplied_result_sha},
        "source_rows": source_rows,
        "lineage": lineage,
        "costs": costs,
    }


__all__ = ["load_recovery_source"]

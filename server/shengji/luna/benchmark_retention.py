"""Fail-closed loading of explicitly reviewed historical mirror attempts.

This module only authenticates and copies old receipts.  It does not retry a
mirror, reconstruct a game, or acquire a provider.  A caller must separately
decide whether a pending slot should be scheduled.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from .benchmark_failure_protocol import PRESERVE_ILLEGAL, attempt_disposition
from .canonical import canonical_json_bytes


SCHEMA = "benchmark-retention-v1"
REPORT_SCHEMA = "w32-llm-benchmark-v1"
MIRROR_SCHEMA = "w32-llm-benchmark-mirror-v1"
LEGACY_SHA256 = "71e197bc10ae73bc25e9bf22e7702b48fd32a49b53830c76321b9c85b09b8949"
LEGACY_KEY = "sol-perfect-seed20261002006-flip1"
LEGACY_ERROR = "IllegalPlay: You must follow suit."
LEGACY_REFERENCE = "https://github.com/jerryyyu/shengji/issues/355#issuecomment-5977135973"


class RetentionRefusal(ValueError):
    """The reviewed retention source does not satisfy its sealed contract."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hex(value: Any, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise RetentionRefusal(f"{label} must be a lowercase SHA256")
    return value


def _reject_constant(value: str) -> None:
    raise RetentionRefusal(f"non-finite JSON constant {value} is not allowed")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RetentionRefusal(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _finite(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RetentionRefusal("non-finite JSON number is not allowed")
    elif isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise RetentionRefusal("JSON object key is not a string")
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _json(raw: bytes, label: str) -> Any:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=_reject_constant)
    except RetentionRefusal:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetentionRefusal(f"{label} is not valid JSON") from exc
    _finite(value)
    return value


def _regular(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RetentionRefusal(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RetentionRefusal(f"{label} must be a regular file")
    return info


def _directory(path: Path, label: str) -> os.stat_result:
    if not path.is_absolute():
        raise RetentionRefusal(f"{label} must be absolute")
    if any(component in (".", "..") for component in path.parts):
        raise RetentionRefusal(f"{label} must not contain traversal components")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            component_info = current.lstat()
        except OSError as exc:
            raise RetentionRefusal(f"{label} is unavailable") from exc
        if stat.S_ISLNK(component_info.st_mode):
            raise RetentionRefusal(f"{label} has a symlink component")
    try:
        info = path.lstat()
    except OSError as exc:
        raise RetentionRefusal(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RetentionRefusal(f"{label} must be a non-symlink directory")
    return info


def _read(path: Path, label: str) -> tuple[bytes, str]:
    before = _regular(path, label)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RetentionRefusal(f"cannot read {label}") from exc
    after = _regular(path, label)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise RetentionRefusal(f"{label} changed while being read")
    return raw, _sha256(raw)


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


def _expected_schedule(config: Mapping[str, Any]) -> tuple[list[str], list[str], list[int]]:
    models = config.get("models")
    information = config.get("information")
    seeds = config.get("seeds")
    if (type(models) is not list or not models
            or any(type(value) is not str or value not in ("sol", "luna")
                   for value in models)
            or len(set(models)) != len(models)):
        raise RetentionRefusal("expected models are invalid")
    if (type(information) is not list or not information
            or any(type(value) is not str or value not in ("actor-only", "perfect")
                   for value in information)
            or len(set(information)) != len(information)):
        raise RetentionRefusal("expected information modes are invalid")
    if (type(seeds) is not list or not seeds
            or any(type(value) is not int or isinstance(value, bool) for value in seeds)
            or len(set(seeds)) != len(seeds)):
        raise RetentionRefusal("expected seeds are invalid")
    return models, information, seeds


def _compare_config(actual: Any, expected: Mapping[str, Any]) -> None:
    if type(actual) is not dict:
        raise RetentionRefusal("result config is not an object")
    fields = ("seeds", "models", "information", "policy",
              "baseline_recipe", "checkpoint")
    for field in fields:
        if field not in expected or field not in actual:
            raise RetentionRefusal(f"result config is missing {field}")
        if not _strict_equal(actual[field], expected[field]):
            raise RetentionRefusal(f"result config {field} disagrees")
    expected_roots = expected.get("prepared_roots_from")
    actual_roots = actual.get("prepared_roots_from")
    if expected_roots is None or actual_roots is None:
        if expected_roots is not None or actual_roots is not None:
            raise RetentionRefusal("prepared root binding disagrees")
    else:
        if (type(expected_roots) is not dict or type(actual_roots) is not dict
                or "result_sha256" not in expected_roots
                or "root_hashes" not in expected_roots
                or "result_sha256" not in actual_roots
                or "root_hashes" not in actual_roots
                or not _strict_equal(
                    actual_roots.get("result_sha256"),
                    expected_roots.get("result_sha256"))
                or not _strict_equal(
                    actual_roots.get("root_hashes"),
                    expected_roots.get("root_hashes"))):
            raise RetentionRefusal("prepared root result binding disagrees")
    for key in ("continue_from", "retained_attempts", "retention_plan",
                "retention_plan_sha256", "retained_from"):
        if key in actual and actual[key] is not None:
            raise RetentionRefusal("retention/continuation chains are refused")


def _row_cost(row: Mapping[str, Any]) -> int:
    calls = row.get("calls", [])
    if type(calls) is not list:
        raise RetentionRefusal("mirror calls must be a list")
    total = 0
    for call in calls:
        if type(call) is not dict:
            raise RetentionRefusal("mirror call must be an object")
        usage = call.get("usage", {})
        if type(usage) is not dict:
            raise RetentionRefusal("mirror call usage must be an object")
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key, 0)
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise RetentionRefusal("token usage must be a nonnegative integer")
            total += value
    return total


def _legacy_copy(row: dict[str, Any], *, key: str, source_sha256: str,
                 listed_sha256: list[str]) -> dict[str, Any] | None:
    if source_sha256 not in listed_sha256:
        return None
    if (key != LEGACY_KEY or source_sha256 != LEGACY_SHA256
            or row.get("complete") is not False
            or row.get("error") != LEGACY_ERROR
            or type(row.get("events")) is not list
            or len(row["events"]) != 23):
        raise RetentionRefusal("listed legacy failure does not match its replay witness")
    event = row["events"][-1]
    if (type(event) is not dict or event.get("seat") != 3
            or event.get("attempted_cards") != ["C7"]):
        raise RetentionRefusal("listed legacy failure has the wrong final event")
    copied = copy.deepcopy(row)
    copied["failure"] = {
        "schema": "benchmark-action-failure-v1",
        "category": "model_illegal_action",
        "stage": "engine_play",
        "seat": 3,
        "attempted_cards": ["C7"],
        "event_index": 22,
    }
    copied["retention_provenance"] = {
        "original_sha256": source_sha256,
        "reference": LEGACY_REFERENCE,
    }
    return copied


def _classify_row(row: dict[str, Any], *, key: str, source_sha256: str,
                  legacy_sha256: list[str]) -> dict[str, Any]:
    complete = row.get("complete")
    if complete is True:
        if "error" in row or "failure" in row:
            raise RetentionRefusal(f"complete row {key} carries a failure")
        score = row.get("signed_levels")
        if (type(score) not in (int, float) or isinstance(score, bool)
                or not math.isfinite(score)):
            raise RetentionRefusal(f"complete row {key} has no finite score")
        _row_cost(row)
        return copy.deepcopy(row)
    if (complete is False and row.get("status") == "not_run"
            and row.get("calls", []) == [] and row.get("events", []) == []
            and "failure" not in row and "signed_levels" not in row):
        _row_cost(row)
        return copy.deepcopy(row)
    disposition = attempt_disposition(row, protocol=PRESERVE_ILLEGAL)
    if disposition == "retained-model-failure":
        _row_cost(row)
        return copy.deepcopy(row)
    copied = _legacy_copy(row, key=key, source_sha256=source_sha256,
                          listed_sha256=legacy_sha256)
    if copied is not None:
        _row_cost(row)
        return copied
    raise RetentionRefusal(f"mirror {key} has an unclassified attempted failure")


def load_retained_attempts(plan_path: str | os.PathLike, plan_sha256: str, *,
                           expected_config: Mapping[str, Any]) -> dict[str, Any]:
    """Authenticate a reviewed historical report and return immutable copies."""
    supplied_plan_sha = _hex(plan_sha256, "plan SHA256")
    if not isinstance(expected_config, Mapping):
        raise RetentionRefusal("expected_config must be an object")
    plan_file = Path(plan_path)
    plan_raw, actual_plan_sha = _read(plan_file, "retention plan")
    if actual_plan_sha != supplied_plan_sha:
        raise RetentionRefusal("retention plan SHA256 mismatch")
    plan = _json(plan_raw, "retention plan")
    if (type(plan) is not dict
            or set(plan) != {"schema", "source_directory", "result_sha256",
                              "legacy_illegal_sha256"}
            or plan["schema"] != SCHEMA):
        raise RetentionRefusal("retention plan schema is invalid")
    result_sha = _hex(plan["result_sha256"], "result SHA256")
    legacy = plan["legacy_illegal_sha256"]
    if (type(legacy) is not list or len(set(legacy)) != len(legacy)
            or any(value != LEGACY_SHA256 for value in legacy)):
        raise RetentionRefusal("legacy allowlist is invalid")
    source_value = plan["source_directory"]
    if type(source_value) is not str or not Path(source_value).is_absolute():
        raise RetentionRefusal("source_directory must be absolute")
    source_dir = Path(source_value)
    _directory(source_dir, "source_directory")
    result_raw, actual_result_sha = _read(source_dir / "result.json", "result.json")
    if actual_result_sha != result_sha:
        raise RetentionRefusal("result SHA256 mismatch")
    result = _json(result_raw, "result.json")
    if (type(result) is not dict or result.get("schema") != REPORT_SCHEMA
            or result.get("mode") != "run"):
        raise RetentionRefusal("source is not a terminal benchmark report")
    for key in ("retained_attempts", "retention", "retention_plan"):
        if key in result and result[key] is not None:
            raise RetentionRefusal("retention chains are refused")
    _compare_config(result.get("config"), expected_config)
    if result.get("prior") not in (None, {}):
        raise RetentionRefusal("continuation chains are refused")
    models, information, seeds = _expected_schedule(expected_config)
    rows_value = result.get("mirrors")
    if type(rows_value) is not list:
        raise RetentionRefusal("terminal report mirrors are missing")
    expected_keys = {
        f"{model}-{mode}-seed{seed}-flip{flip}"
        for model in models for mode in information for seed in seeds
        for flip in (0, 1)}
    rows_by_key: dict[str, dict[str, Any]] = {}
    for row in rows_value:
        if type(row) is not dict or type(row.get("key")) is not str:
            raise RetentionRefusal("terminal mirror row is malformed")
        key = row["key"]
        if key in rows_by_key:
            raise RetentionRefusal("terminal mirror keys are not unique")
        rows_by_key[key] = row
    if set(rows_by_key) != expected_keys:
        raise RetentionRefusal("terminal report does not cover exact schedule")
    retained: dict[str, dict[str, Any]] = {}
    source_rows: dict[str, dict[str, Any]] = {}
    prior_cost = 0
    for model in models:
        for mode in information:
            for seed in seeds:
                for flip in (0, 1):
                    key = f"{model}-{mode}-seed{seed}-flip{flip}"
                    row = rows_by_key[key]
                    if (row.get("schema") != MIRROR_SCHEMA
                            or row.get("arm") != f"{model}-{mode}"
                            or row.get("model") != model
                            or row.get("information") != mode
                            or type(row.get("seed")) is not int
                            or isinstance(row.get("seed"), bool)
                            or row.get("seed") != seed
                            or type(row.get("flip")) is not int
                            or isinstance(row.get("flip"), bool)
                            or row.get("flip") != flip):
                        raise RetentionRefusal(f"mirror identity mismatch for {key}")
                    mirror_path = source_dir / f"mirror-{model}-{mode}-{seed}-{flip}.json"
                    mirror_raw, mirror_sha = _read(mirror_path, f"mirror {key}")
                    mirror_obj = _json(mirror_raw, f"mirror {key}")
                    if (type(mirror_obj) is not dict
                            or canonical_json_bytes(mirror_obj)
                            != canonical_json_bytes(row)):
                        raise RetentionRefusal(f"mirror {key} disagrees with report")
                    prior_cost += _row_cost(row)
                    retained[key] = _classify_row(
                        row, key=key, source_sha256=mirror_sha,
                        legacy_sha256=legacy)
                    source_rows[key] = {
                        "row": copy.deepcopy(mirror_obj),
                        "path": str(mirror_path),
                        "sha256": mirror_sha,
                    }
    return {"path": str(source_dir), "result_sha256": result_sha,
            "plan_sha256": supplied_plan_sha, "rows": retained,
            "source_rows": source_rows, "prior_cost_tokens": prior_cost}


__all__ = ["RetentionRefusal", "load_retained_attempts"]

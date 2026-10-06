"""Assemble one authenticated stage-1 seal plan from a terminal campaign.

This module only prepares a metadata-bound plan.  It never launches a row,
opens a model/provider, or publishes a scientific readout.  ``run_once``
provides the exclusive output claim and leaves a refusal/partial claim on any
failure, so callers cannot silently retry a failed assembly.

The caller must establish terminal process state, exclusive ownership and the
reviewed reader/runtime pins before execution. ``--execute`` is not RELEASE.
After metadata admission this hashes row-result bytes, but never parses them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from scripts.sealed_production_llm_panel_readout import admit_stage1_metadata
from shengji.luna.benchmark_readout_receipt import run_once


SCHEMA = "sol-feedback-on-stage1-seals-v1"
METADATA_LIMIT = 8 << 20
RESULT_LIMIT = 512 << 20
ZERO_SHA256 = "0" * 64
_CHUNK = 1024 * 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and len(value) == 64
             and all(char in "0123456789abcdef" for char in value),
             f"{label} must be a lowercase SHA256")
    return value


def _safe_path(path: Path, label: str) -> Path:
    _require(path.is_absolute() and "." not in path.parts and ".." not in path.parts,
             f"{label} must be absolute without traversal")
    current = Path(path.anchor)
    for component in path.parts[1:-1]:
        current /= component
        info = current.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
                 f"{label} has an unsafe parent")
    return path


def _stamp(path: Path, label: str) -> tuple[int, int, int, int, int]:
    _safe_path(path, label)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode),
             f"{label} must be a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _decode(raw: bytes, label: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f"{label} has duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"{label} contains non-finite JSON")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc


def _read_metadata(path: Path, label: str,
                   expected: str | None = None) -> tuple[Any, tuple, str]:
    before = _stamp(path, label)
    _require(before[2] <= METADATA_LIMIT, f"{label} exceeds metadata bound")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"cannot open {label}") from exc
    try:
        opened = os.fstat(descriptor)
        _require(stat.S_ISREG(opened.st_mode), f"{label} must be a regular file")
        digest = hashlib.sha256()
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= METADATA_LIMIT, f"{label} exceeds metadata bound")
            digest.update(chunk)
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError(f"cannot read {label}") from exc
    finally:
        os.close(descriptor)
    _require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns,
              opened.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                      after.st_mtime_ns, after.st_ctime_ns),
             f"{label} changed while being read")
    _require(before == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                        after.st_ctime_ns), f"{label} changed before opening")
    actual = digest.hexdigest()
    if expected is not None:
        _require(actual == _sha(expected, label + " digest"), f"{label}: SHA mismatch")
    _require(total == before[2], f"{label} short read")
    return _decode(b"".join(chunks), label), before, actual


def _hash_result_once(path: Path, label: str) -> tuple[str, tuple[int, int, int, int, int]]:
    """Hash one result through an O_NOFOLLOW regular-file descriptor."""
    before = _stamp(path, label)
    _require(before[2] <= RESULT_LIMIT, f"{label} exceeds result bound")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"cannot open {label}") from exc
    try:
        opened = os.fstat(descriptor)
        _require(stat.S_ISREG(opened.st_mode), f"{label} must be a regular file")
        _require(opened.st_size <= RESULT_LIMIT, f"{label} exceeds result bound")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= RESULT_LIMIT, f"{label} exceeds result bound")
            digest.update(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError(f"cannot read {label}") from exc
    finally:
        os.close(descriptor)
    _require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns,
              opened.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                      after.st_mtime_ns, after.st_ctime_ns),
             f"{label} changed while being hashed")
    _require(before == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                        after.st_ctime_ns), f"{label} changed before hashing")
    _require(total == before[2], f"{label} short read")
    return digest.hexdigest(), (after.st_dev, after.st_ino, after.st_size,
                               after.st_mtime_ns, after.st_ctime_ns)


def _build(config_path: Path, expected_sha256: str, output_dir: Path) -> dict[str, Any]:
    _sha(expected_sha256, "config digest")
    config, config_stamp, _ = _read_metadata(config_path, "stage1 config", expected_sha256)
    from scripts.launch_production_llm_panel import STAGE1_ROWS, STAGE1_SCHEMA

    _require(config.get("schema") == STAGE1_SCHEMA and config.get("rows") == list(STAGE1_ROWS),
             "stage1 fresh recipe required")
    campaign_output = _safe_path(Path(config.get("output", "")), "campaign output")
    _require(campaign_output != output_dir, "plan output must be separate from campaign output")

    metadata_stamps = {config_path: config_stamp}

    def ref(path: Path, label: str, expected: str | None = None):
        _, stamp, digest = _read_metadata(_safe_path(path, label), label, expected)
        metadata_stamps[path] = stamp
        return {"path": str(path), "sha256": digest}

    plan = {
        "schema": SCHEMA,
        "campaign": {
            "config": {"path": str(config_path), "sha256": expected_sha256},
            "output_config": ref(campaign_output / "config.json", "stage1 output config"),
            "terminal": ref(campaign_output / "terminal.json", "stage1 terminal"),
            "summary": ref(campaign_output / "stage1-summary.json", "stage1 summary"),
        },
        "rows": {
            row: {
                "result": {"path": str(campaign_output / row / "result.json"),
                           "sha256": ZERO_SHA256},
                "terminal": ref(campaign_output / (row + ".terminal.json"), row + " terminal"),
                "accounting": ref(campaign_output / (row + ".accounting.json"), row + " accounting"),
            }
            for row in STAGE1_ROWS
        },
    }

    prepared_roots = _safe_path(Path(config["prepared_roots"]) / "result.json", "prepared roots")
    # Authenticate and bound the roots metadata before the shared helper reads
    # it.  The helper remains the sole semantic admission gate.
    ref(prepared_roots, "stage1 roots", config["prepared_roots_sha256"])
    # This is the complete metadata gate.  It intentionally sees only
    # placeholder result digests and never opens a row result.
    admit_stage1_metadata(plan)
    for path, stamp in metadata_stamps.items():
        _require(_stamp(path, "stage1 metadata") == stamp,
                 f"stage1 metadata changed during admission: {path}")

    result_stamps = {}
    for row in STAGE1_ROWS:
        result_path = _safe_path(campaign_output / row / "result.json", row + " result")
        digest, stamp = _hash_result_once(result_path, row + " result")
        plan["rows"][row]["result"]["sha256"] = digest
        result_stamps[result_path] = stamp

    for path, stamp in result_stamps.items():
        _require(_stamp(path, "stage1 result") == stamp,
                 f"stage1 result changed after hashing: {path}")

    for path, stamp in metadata_stamps.items():
        _require(_stamp(path, "stage1 metadata") == stamp,
                 f"stage1 metadata changed while hashing results: {path}")
    return plan


def prepare_stage1_seal_plan(config_path: str | os.PathLike[str], expected_sha256: str,
                             output_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Claim ``output_dir`` and write its plan as ``result.json`` exactly once."""
    config = _safe_path(Path(config_path), "config")
    output = _safe_path(Path(output_dir), "plan output")
    identity = {"schema": SCHEMA, "config": {"path": str(config), "sha256": expected_sha256}}
    return run_once(output, identity, lambda: _build(config, expected_sha256, output))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--execute", action="store_true",
                        help="required acknowledgement for hashing and sealing row-result bytes")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("refusing to read inputs without --execute")
    prepare_stage1_seal_plan(args.config, args.config_sha256, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

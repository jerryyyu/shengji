#!/usr/bin/env python3
"""Bounded metadata preview, not a provenance validator or sealed-data reader."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

DEFAULT_LIMIT = 16 * 1024 * 1024
SAMPLES = 5
TEXT_LIMIT = 240


def scalar(value):
    # Never stringify arbitrary nested values or huge numeric literals.
    return value[:TEXT_LIMIT] if isinstance(value, str) else None


def summarize(value):
    if not isinstance(value, dict):
        raise ValueError("receipt must be an object")
    data = value.get("data")
    rows = data if isinstance(data, list) else []
    result = {"top_level_key_count": len(value), "data_shape": type(data).__name__,
              "data_count": len(rows), "data_omitted": max(0, len(rows) - SAMPLES),
              "string_limit": TEXT_LIMIT, "data": [], "init_sha256": None}
    init = value.get("init")
    if isinstance(init, dict):
        result["init_sha256"] = scalar(init.get("sha256"))
    for row in rows[:SAMPLES]:
        row = row if isinstance(row, dict) else {}
        manifests = row.get("manifests")
        manifests = manifests if isinstance(manifests, list) else []
        result["data"].append({
            "root": scalar(row.get("root")), "manifest_count": len(manifests),
            "manifests_omitted": max(0, len(manifests) - SAMPLES),
            "manifests": [{key: scalar(item.get(key)) for key in ("path", "schema", "sha256")}
                          if isinstance(item, dict) else {} for item in manifests[:SAMPLES]],
        })
    return result


def read_summary(path, max_input_bytes=DEFAULT_LIMIT):
    if max_input_bytes <= 0:
        raise ValueError("input limit must be positive")
    # Nonblocking open allows us to reject a FIFO without waiting for a writer.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("input must be a regular file")
        if info.st_size > max_input_bytes:
            raise ValueError("receipt exceeds input limit; use a targeted projection")
        raw = stream.read(max_input_bytes + 1)
        if len(raw) > max_input_bytes:
            raise ValueError("receipt grew beyond input limit")
    return summarize(json.loads(raw))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    try:
        result = read_summary(args.receipt, args.max_input_bytes)
    except (OSError, ValueError, RecursionError):
        # JSON errors and OS paths can contain sensitive/unbounded input.
        print("receipt preview refused: check regular-file type, size limit and JSON object format", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

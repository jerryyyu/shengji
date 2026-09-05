"""Aggregate PT-Luna private journal token and prompt-byte telemetry.

This is an offline profiler.  It reads sealed journal JSON only; it never
reopens provider calls, writes artifacts, or prints private prompt contents.
Prompt sizes are UTF-8 byte measurements, not tokenizer token counts.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


RECORD_NAME = re.compile(r"^\d{6}-(response|refusal)\.json$")
PROMPT_MARKER = b"DECISION_PACKET_JSON\n"
USAGE_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")).encode("ascii")


def _field_bytes(key: str, value: object) -> int:
    """Bytes for one JSON object field, excluding its surrounding braces."""
    return len(_canonical({key: value})) - 2


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    if any(not _int(value.get(key)) for key in USAGE_FIELDS):
        return None
    result = {key: int(value[key]) for key in USAGE_FIELDS}
    # Totals are derived usage, never a reserve/settle ledger sum.
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        return None
    if result["cached_input_tokens"] > result["input_tokens"]:
        return None
    if result["reasoning_output_tokens"] > result["output_tokens"]:
        return None
    if "wall_ms" in value and not _int(value["wall_ms"]):
        return None
    return result


def _zero_usage() -> dict[str, int]:
    return {key: 0 for key in USAGE_FIELDS}


def _add_usage(target: dict[str, int], value: dict[str, int]) -> None:
    for key in USAGE_FIELDS:
        target[key] += value[key]


def _usage_view(value: dict[str, int], count: int, call_count: int) -> dict[str, int]:
    result = dict(value)
    result["uncached_input_tokens"] = (
        result["input_tokens"] - result["cached_input_tokens"])
    result["non_reasoning_output_tokens"] = (
        result["output_tokens"] - result["reasoning_output_tokens"])
    result["record_count"] = count
    result["call_count"] = call_count
    return result


def _attempt_key(record: dict[str, Any], path: Path) -> str:
    attempt = record.get("attempt")
    if isinstance(attempt, dict):
        for key in ("attempt_sha256", "logical_packet_sha256"):
            value = attempt.get(key)
            if isinstance(value, str) and value:
                return value
    # The fallback is only an identity for malformed synthetic records; it
    # does not expose the path in output.
    return path.parent.parent.name


def _route(record: dict[str, Any], path: Path) -> str:
    if path.name.endswith("-response.json"):
        return "accepted"
    if path.name.endswith("-refusal.json"):
        return "refusal"
    if record.get("kind") == "model-response-sealed":
        return "accepted"
    return "refusal"


def _private(record: dict[str, Any], route: str) -> object:
    if route == "accepted":
        response = record.get("response")
        if isinstance(response, dict):
            return response.get("provider_private_evidence")
        return None
    return record.get("provider_private_evidence")


def _private_usage(record: dict[str, Any], route: str) -> dict[str, int] | None:
    private = _private(record, route)
    if not isinstance(private, dict):
        return None
    if route == "accepted":
        response = private.get("response")
        return _usage(response.get("usage")) if isinstance(response, dict) else None
    return _usage(private.get("usage"))


def _provider_hash(record: dict[str, Any]) -> str | None:
    response = record.get("response")
    value = response.get("provider_response_sha256") if isinstance(response, dict) else None
    return value if isinstance(value, str) and value else None


def _decode_prompt(record: dict[str, Any], route: str) -> tuple[bytes, dict[str, Any]] | None:
    private = _private(record, route)
    if not isinstance(private, dict) or not isinstance(private.get("prompt_base64"), str):
        return None
    try:
        raw = base64.b64decode(private["prompt_base64"], validate=True)
        text = raw.decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error):
        return None
    marker_text = PROMPT_MARKER.decode("ascii")
    marker = text.find(marker_text)
    if marker < 0:
        return None
    packet_start = marker + len(marker_text)
    packet_text = text[packet_start:]
    try:
        packet, chars = json.JSONDecoder().raw_decode(packet_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(packet, dict):
        return None
    packet_raw = packet_text[:chars].encode("utf-8")
    # The JSON decoder's character offset is converted back to bytes so
    # non-ASCII packet values remain measured correctly.
    prefix = text[:marker].encode("utf-8")
    suffix = packet_text[chars:].encode("utf-8")
    state = packet.get("state")
    return raw, {
        "prefix": prefix,
        "packet": packet_raw,
        "suffix": suffix,
        "top_level": {str(key): _field_bytes(str(key), value)
                       for key, value in packet.items()},
        "state": ({str(key): _field_bytes(str(key), value)
                   for key, value in state.items()}
                  if isinstance(state, dict) else {}),
        "metadata_hash_bytes": _metadata_hash_bytes(packet),
        "metadata_hash_occurrences": _metadata_hash_occurrences(packet),
    }


def _metadata_hash_bytes(value: object) -> int:
    if isinstance(value, list):
        return sum(_metadata_hash_bytes(child) for child in value)
    if not isinstance(value, dict):
        return 0
    total = 0
    for key, child in value.items():
        if key == "schema" or key.endswith("_sha256"):
            total += _field_bytes(str(key), child)
        else:
            total += _metadata_hash_bytes(child)
    return total


def _metadata_hash_occurrences(value: object) -> int:
    if isinstance(value, dict):
        return sum((1 if key == "schema" or key.endswith("_sha256") else 0)
                   + _metadata_hash_occurrences(child)
                   for key, child in value.items())
    if isinstance(value, list):
        return sum(_metadata_hash_occurrences(child) for child in value)
    return 0


def _common_prefix(rows: list[bytes]) -> int:
    if not rows:
        return 0
    length = min(map(len, rows))
    for index in range(length):
        byte = rows[0][index]
        if any(row[index] != byte for row in rows[1:]):
            return index
    return length


def _empty_prompt() -> dict[str, Any]:
    return {
        "basis": "UTF-8 bytes; NOT tokenizer exact tokens",
        "prompt_count": 0,
        "total_bytes": 0,
        "static_prefix_bytes": 0,
        "unique_static_prefix_bytes": 0,
        "duplicate_static_prefix_bytes": 0,
        "common_prefix_bytes": 0,
        "duplicate_common_prefix_bytes": 0,
        "packet_bytes": 0,
        "marker_bytes": 0,
        "suffix_bytes": 0,
        "top_level_fields": {},
        "state_fields": {},
        "metadata_hash_overhead_bytes": 0,
        "metadata_hash_occurrences": 0,
    }


def _prompt_aggregate(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        return _empty_prompt()
    result = _empty_prompt()
    prefixes = [part["prefix"] for part in parts]
    result["prompt_count"] = len(parts)
    result["total_bytes"] = sum(len(part["raw"]) for part in parts)
    result["static_prefix_bytes"] = sum(len(value) for value in prefixes)
    unique_prefixes = set(prefixes)
    result["unique_static_prefix_bytes"] = sum(map(len, unique_prefixes))
    result["duplicate_static_prefix_bytes"] = (
        result["static_prefix_bytes"] - result["unique_static_prefix_bytes"])
    result["common_prefix_bytes"] = _common_prefix(prefixes)
    result["duplicate_common_prefix_bytes"] = (
        result["common_prefix_bytes"] * max(len(parts) - 1, 0))
    result["packet_bytes"] = sum(len(part["packet"]) for part in parts)
    result["marker_bytes"] = len(PROMPT_MARKER) * len(parts)
    result["suffix_bytes"] = sum(len(part["suffix"]) for part in parts)
    for part in parts:
        for key, value in part["top_level"].items():
            result["top_level_fields"][key] = result["top_level_fields"].get(key, 0) + value
        for key, value in part["state"].items():
            result["state_fields"][key] = result["state_fields"].get(key, 0) + value
        result["metadata_hash_overhead_bytes"] += part["metadata_hash_bytes"]
        result["metadata_hash_occurrences"] += part["metadata_hash_occurrences"]
    return result


def _record_paths(roots: Iterable[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if root.is_file() and RECORD_NAME.match(root.name):
            paths.append(root)
        elif root.is_dir():
            paths.extend(path for path in root.rglob("*.json")
                         if RECORD_NAME.match(path.name))
    return sorted(set(paths), key=lambda path: str(path))


def profile_roots(roots: Iterable[str | Path], *, sample_limit: int | None = None) -> dict[str, Any]:
    """Return a public aggregate for private journal roots."""
    root_paths = [Path(root) for root in roots]
    paths = _record_paths(root_paths)
    if sample_limit is not None:
        if sample_limit < 0:
            raise ValueError("sample limit must be non-negative")
        paths = paths[:sample_limit]
    diagnostics = {
        "files_seen": len(paths), "malformed_json": 0,
        "unknown_telemetry_count": 0, "unknown_prompt_count": 0,
        "duplicate_accepted_count": 0, "accepted_refusal_conflicts": 0,
    }
    # First select one route per logical call.  A committed accepted response
    # wins over a stale refusal for the same call identity.
    selected: dict[tuple[str, int], tuple[str, dict[str, Any], Path]] = {}
    accepted_raw = refusal_raw = 0
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            diagnostics["malformed_json"] += 1
            diagnostics["unknown_telemetry_count"] += 1
            continue
        if not isinstance(value, dict):
            diagnostics["malformed_json"] += 1
            diagnostics["unknown_telemetry_count"] += 1
            continue
        route = _route(value, path)
        if route == "accepted":
            accepted_raw += 1
        else:
            refusal_raw += 1
        attempt = _attempt_key(value, path)
        call_index = value.get("call_index")
        if not isinstance(call_index, int) or isinstance(call_index, bool):
            call_index = -1
        key = (attempt, call_index)
        prior = selected.get(key)
        if prior is None:
            selected[key] = (route, value, path)
        elif prior[0] != route:
            diagnostics["accepted_refusal_conflicts"] += 1
            if route == "accepted":
                selected[key] = (route, value, path)

    accepted_hashes: set[str] = set()
    accepted_count = refusal_count = 0
    usage_by_route = {"accepted": _zero_usage(), "refusal": _zero_usage()}
    count_by_route = {"accepted": 0, "refusal": 0}
    known_count_by_route = {"accepted": 0, "refusal": 0}
    prompt_parts: list[dict[str, Any]] = []
    for route, record, path in sorted(selected.values(), key=lambda row: str(row[2])):
        if route == "accepted":
            provider_hash = _provider_hash(record)
            if provider_hash is not None and provider_hash in accepted_hashes:
                diagnostics["duplicate_accepted_count"] += 1
                continue
            if provider_hash is not None:
                accepted_hashes.add(provider_hash)
            accepted_count += 1
        else:
            refusal_count += 1
        count_by_route[route] += 1
        usage = _private_usage(record, route)
        if usage is None:
            diagnostics["unknown_telemetry_count"] += 1
        else:
            _add_usage(usage_by_route[route], usage)
            known_count_by_route[route] += 1
        decoded = _decode_prompt(record, route)
        if decoded is None:
            diagnostics["unknown_prompt_count"] += 1
        else:
            raw, part = decoded
            part["raw"] = raw
            prompt_parts.append(part)

    aggregate_usage = _zero_usage()
    for route in ("accepted", "refusal"):
        _add_usage(aggregate_usage, usage_by_route[route])
    return {
        "schema": "pt-luna-token-profile-v1",
        "root_count": len(root_paths),
        "sample_limit": sample_limit,
        "records": {
            "files_seen": diagnostics["files_seen"],
            "accepted_raw": accepted_raw,
            "refusal_raw": refusal_raw,
            "accepted_unique": accepted_count,
            "refusal_unique": refusal_count,
        },
        "usage": {
            "accepted": _usage_view(usage_by_route["accepted"], known_count_by_route["accepted"], count_by_route["accepted"]),
            "refusal": _usage_view(usage_by_route["refusal"], known_count_by_route["refusal"], count_by_route["refusal"]),
            "aggregate": _usage_view(aggregate_usage,
                                      known_count_by_route["accepted"] + known_count_by_route["refusal"],
                                      count_by_route["accepted"] + count_by_route["refusal"]),
        },
        "prompt_bytes": _prompt_aggregate(prompt_parts),
        "diagnostics": diagnostics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("roots", nargs="+", type=Path,
                        help="private run root(s), or a response/refusal JSON file")
    parser.add_argument("--sample-limit", type=int,
                        help="profile only the first N records in sorted path order")
    args = parser.parse_args(argv)
    try:
        result = profile_roots(args.roots, sample_limit=args.sample_limit)
    except ValueError as exc:
        parser.error(str(exc))
    json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

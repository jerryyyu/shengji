"""Closed canonical JSON encoding shared by every PT-Luna artifact hash."""

from __future__ import annotations

import json


def canonical_json_bytes(value: object) -> bytes:
    """Return the closed canonical encoding used for every sealed hash."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


__all__ = ["canonical_json_bytes"]

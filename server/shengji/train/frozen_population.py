"""Opt-in population binding for value-only additions; no I/O or split fallback.

Callers supply authenticated base-population pins separately from the manifest
and identify base and added stores separately. This module does not authenticate
store provenance, candidate tensors, or the effective policy-row receipt.
"""
from collections.abc import Mapping, Sequence
import hashlib
import re

PARTS = ("train", "val", "test")
SCHEMA = "shengji-frozen-population-v1"


def _keys(values, label):
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(k, str) or re.fullmatch(r"deck:[0-9a-f]{64}", k) is None
        for k in values
    ):
        raise ValueError(f"{label}: full deal-key list required")
    result = set(values)
    if len(result) != len(values):
        raise ValueError(f"{label}: duplicate deal keys")
    return result


def bind_frozen_population(manifest: Mapping, *, expected_digests: Mapping,
                           base_keys: Sequence[str], added_keys: Sequence[str]):
    """Keep every base assignment; add only explicitly named, disjoint fit deals.

    Reject any missing/extra base key and any addition colliding with the base
    (including train). Never silently repartition or exclude a pinned deal.
    Caller must recheck the resulting val/test after init-exposure processing.
    """
    if not isinstance(manifest, Mapping) or set(manifest) != {"schema", *PARTS}:
        raise ValueError("invalid frozen population manifest fields")
    if manifest["schema"] != SCHEMA:
        raise ValueError("invalid frozen population schema")
    if not isinstance(expected_digests, Mapping) or set(expected_digests) != set(PARTS):
        raise ValueError("independent train/val/test digest pins required")
    assignment = {}
    for part in PARTS:
        keys = _keys(manifest[part], part)
        if not keys:
            raise ValueError(f"{part}: empty frozen partition")
        digest = hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest()
        if digest != expected_digests[part]:
            raise ValueError(f"{part}: frozen digest mismatch")
        if keys & assignment.keys():
            raise ValueError("overlapping frozen partitions")
        assignment.update(dict.fromkeys(keys, part))
    base = _keys(base_keys, "base stores")
    added = _keys(added_keys, "added stores")
    if base != assignment.keys():
        raise ValueError("base stores differ from frozen population")
    if added & base:
        raise ValueError("added stores collide with frozen base")
    assignment.update(dict.fromkeys(added, "train"))
    return assignment
